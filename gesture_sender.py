import cv2
import time
import math
import importlib
from pathlib import Path


# =========================
# 文件通信设置
# TouchDesigner 会读取这个文件
# =========================
STATE_PATH = Path(__file__).resolve().parent / "gesture_state.txt"


# =========================
# 显示设置
# =========================
# False = 隐藏摄像头窗口，适合展示
# True = 显示摄像头窗口，适合调试
SHOW_CAMERA_WINDOW = False


# =========================
# 灵敏度设置
# =========================
OPEN_OFFSET = 0.12
FIST_FULL = 1.05

# Python 端平滑：越大越稳，越小越跟手
SMOOTH_OLD = 0.82
SMOOTH_NEW = 0.18


# =========================
# MediaPipe 手部识别
# 本项目用 Python 3.11，不要用 Python 3.14
# =========================
mp_hands = importlib.import_module("mediapipe.python.solutions.hands")
mp_draw = importlib.import_module("mediapipe.python.solutions.drawing_utils")

hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    model_complexity=1,
    min_detection_confidence=0.65,
    min_tracking_confidence=0.65
)


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def smoothstep(x):
    x = clamp(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def dist_xy(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def angle_abc(a, b, c):
    """
    计算 a-b-c 三点在 b 点的夹角。
    手指越直，角度越接近 180。
    手指越弯，角度越小。
    """
    ab = (a[0] - b[0], a[1] - b[1])
    cb = (c[0] - b[0], c[1] - b[1])

    ab_len = math.hypot(ab[0], ab[1])
    cb_len = math.hypot(cb[0], cb[1])

    if ab_len < 1e-6 or cb_len < 1e-6:
        return 180.0

    dot = ab[0] * cb[0] + ab[1] * cb[1]
    cos_v = dot / (ab_len * cb_len)
    cos_v = clamp(cos_v, -1.0, 1.0)

    return math.degrees(math.acos(cos_v))


def write_state(value):
    """
    写入连续手势值：
    0.000 = 完全张开 / 没手 / 球体完全散开
    0.500 = 半握拳 / 球体聚合一半
    1.000 = 完全握拳 / 球体完全聚合
    """
    try:
        value = clamp(float(value), 0.0, 1.0)
        STATE_PATH.write_text(f"{value:.3f}", encoding="utf-8")
    except Exception as e:
        print("写入 gesture_state.txt 失败：", e)


def finger_curl_score(lm, tip_id, dip_id, pip_id, mcp_id):
    """
    计算单根手指弯曲程度。
    0 = 张开
    1 = 弯曲
    """

    wrist = lm[0]
    tip = lm[tip_id]
    dip = lm[dip_id]
    pip = lm[pip_id]
    mcp = lm[mcp_id]

    wrist_xy = (wrist.x, wrist.y)
    tip_xy = (tip.x, tip.y)
    dip_xy = (dip.x, dip.y)
    pip_xy = (pip.x, pip.y)
    mcp_xy = (mcp.x, mcp.y)

    # 1. 关节角度
    angle1 = angle_abc(mcp_xy, pip_xy, tip_xy)
    angle2 = angle_abc(pip_xy, dip_xy, tip_xy)

    angle_open_1 = clamp((angle1 - 110.0) / (175.0 - 110.0), 0.0, 1.0)
    angle_open_2 = clamp((angle2 - 125.0) / (178.0 - 125.0), 0.0, 1.0)

    angle_curl = 1.0 - (angle_open_1 * 0.60 + angle_open_2 * 0.40)

    # 2. 指尖离手腕的伸展比例
    mcp_wrist = dist_xy(mcp_xy, wrist_xy)
    tip_wrist = dist_xy(tip_xy, wrist_xy)

    ratio = tip_wrist / max(mcp_wrist, 1e-6)
    ratio_open = clamp((ratio - 1.30) / (2.18 - 1.30), 0.0, 1.0)
    ratio_curl = 1.0 - ratio_open

    # 3. 竖直方向判断
    vertical_ref = abs(mcp.y - pip.y) + 1e-6
    y_curl = clamp((tip.y - pip.y) / vertical_ref, 0.0, 1.0)

    curl = angle_curl * 0.30 + ratio_curl * 0.24 + y_curl * 0.46

    return clamp(curl, 0.0, 1.0)


def thumb_curl_score(lm):
    """
    拇指弯曲程度。
    0 = 张开
    1 = 收起
    """

    thumb_tip = lm[4]
    thumb_ip = lm[3]
    thumb_mcp = lm[2]
    index_mcp = lm[5]
    wrist = lm[0]

    thumb_tip_xy = (thumb_tip.x, thumb_tip.y)
    thumb_ip_xy = (thumb_ip.x, thumb_ip.y)
    thumb_mcp_xy = (thumb_mcp.x, thumb_mcp.y)
    index_mcp_xy = (index_mcp.x, index_mcp.y)
    wrist_xy = (wrist.x, wrist.y)

    angle = angle_abc(thumb_mcp_xy, thumb_ip_xy, thumb_tip_xy)
    angle_open = clamp((angle - 115.0) / (170.0 - 115.0), 0.0, 1.0)
    angle_curl = 1.0 - angle_open

    palm_ref = dist_xy(index_mcp_xy, wrist_xy)
    thumb_dist = dist_xy(thumb_tip_xy, index_mcp_xy) / max(palm_ref, 1e-6)

    dist_open = clamp((thumb_dist - 0.55) / (1.35 - 0.55), 0.0, 1.0)
    dist_curl = 1.0 - dist_open

    curl = angle_curl * 0.30 + dist_curl * 0.70

    return clamp(curl, 0.0, 1.0)


def calc_grip_value(hand_landmarks):
    """
    根据手指弯曲程度计算 0~1 连续值。
    0 = 完全张开
    1 = 完全握拳
    """

    lm = hand_landmarks.landmark

    index_curl = finger_curl_score(lm, 8, 7, 6, 5)
    middle_curl = finger_curl_score(lm, 12, 11, 10, 9)
    ring_curl = finger_curl_score(lm, 16, 15, 14, 13)
    pinky_curl = finger_curl_score(lm, 20, 19, 18, 17)
    thumb_curl = thumb_curl_score(lm)

    raw_grip = (
        index_curl * 0.25
        + middle_curl * 0.25
        + ring_curl * 0.22
        + pinky_curl * 0.18
        + thumb_curl * 0.10
    )

    grip = (raw_grip - OPEN_OFFSET) / max(FIST_FULL - OPEN_OFFSET, 1e-6)
    grip = clamp(grip, 0.0, 1.0)

    grip = smoothstep(grip)

    if grip < 0.045:
        grip = 0.0

    if grip > 0.965:
        grip = 1.0

    return clamp(grip, 0.0, 1.0)


# =========================
# 摄像头
# =========================
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)

if not cap.isOpened():
    cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("摄像头打开失败。请检查摄像头是否被其他软件占用。")
    write_state(0.0)
    raise SystemExit


smooth_value = 0.0
write_state(smooth_value)

last_write_time = 0
last_print_time = 0

print("手势识别已启动。")
print("当前是展示模式：摄像头窗口已隐藏。")
print("这个项目请使用 Python 3.11，不要用 Python 3.14。")
print("gesture_state.txt 写入位置：")
print(STATE_PATH)
print("完全张开：接近 0.000")
print("半握拳：0.300 ~ 0.700")
print("完全握拳：接近 1.000")
print("退出方式：在这个终端按 Ctrl + C")
print()


try:
    while True:
        ret, frame = cap.read()

        if not ret:
            print("摄像头读取失败。")
            write_state(0.0)
            break

        frame = cv2.flip(frame, 1)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = hands.process(rgb)

        target_value = 0.0
        status_text = "NO HAND"

        if result.multi_hand_landmarks:
            hand_landmarks = result.multi_hand_landmarks[0]
            target_value = calc_grip_value(hand_landmarks)

            if target_value > 0.82:
                status_text = "FIST"
            elif target_value > 0.25:
                status_text = "HALF"
            else:
                status_text = "OPEN"

            if SHOW_CAMERA_WINDOW:
                mp_draw.draw_landmarks(
                    frame,
                    hand_landmarks,
                    mp_hands.HAND_CONNECTIONS
                )

        # 平滑处理
        smooth_value = smooth_value * SMOOTH_OLD + target_value * SMOOTH_NEW

        # 没有手时更快归零
        if not result.multi_hand_landmarks:
            smooth_value = smooth_value * 0.55

        # 张开时加速压到 0
        if target_value < 0.035:
            smooth_value = smooth_value * 0.58

        smooth_value = clamp(smooth_value, 0.0, 1.0)

        now = time.time()

        # 约 60fps 写入
        if now - last_write_time > 0.016:
            write_state(smooth_value)
            last_write_time = now

        # 终端里低频显示状态，不刷屏
        if now - last_print_time > 0.25:
            print(f"\r状态：{status_text:<7}  GRIP: {smooth_value:.3f}   ", end="")
            last_print_time = now

        # 调试模式才显示摄像头窗口
        if SHOW_CAMERA_WINDOW:
            h, w, _ = frame.shape

            cv2.rectangle(frame, (20, 20), (610, 95), (0, 0, 0), -1)

            cv2.putText(
                frame,
                f"{status_text}  GRIP: {smooth_value:.3f}",
                (35, 65),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.95,
                (0, 255, 255),
                2
            )

            cv2.putText(
                frame,
                "Press Q / ESC to quit",
                (35, h - 35),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (200, 200, 200),
                2
            )

            cv2.imshow("Gesture Sender Continuous Grip", frame)

            key = cv2.waitKey(1) & 0xFF

            if key == ord("q") or key == 27:
                break

except KeyboardInterrupt:
    print("\n正在退出手势识别程序...")


write_state(0.0)

cap.release()
cv2.destroyAllWindows()

print("\n已退出。gesture_state.txt 已写入 0。")
