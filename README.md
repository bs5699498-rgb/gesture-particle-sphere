# Gesture Particle Sphere

这是一个 Python + MediaPipe + OpenCV + TouchDesigner 的手势粒子球项目。

项目通过 `gesture_sender.py` 使用摄像头和 MediaPipe 识别手势，并把运行状态写入 `gesture_state.txt`。TouchDesigner 工程 `gesture_particle_sphere_final.toe` 读取该运行时状态，用手势控制粒子球效果。

## 运行环境

- Python 3.11
- TouchDesigner

## 安装依赖

```bash
pip install -r requirements.txt
```

## 文件说明

- `gesture_sender.py`: Python 手势识别与状态发送脚本
- `gesture_particle_sphere_final.toe`: TouchDesigner 粒子球工程文件
- `gesture_state.txt`: 运行时自动生成的状态文件，不提交到 Git
