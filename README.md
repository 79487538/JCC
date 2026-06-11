# JCC S17 AI Assistant

JCC S17 AI Assistant 是一个金铲铲 S17 星神版本 AI 推荐助手项目，包含：

- FastAPI 后端
- Electron + React 客户端
- 卡密激活系统
- 手动局势推荐
- 截图识别推荐
- 多模型 AI Provider 抽象层

## 文档入口

- [用户使用教程](docs/用户使用教程.md)
- [管理员部署说明](docs/管理员部署说明.md)
- [商业化运营说明](docs/商业化运营说明.md)
- [免责声明](docs/免责声明.md)

## 快速启动后端

```powershell
cd D:\JCC\jcc-s17-ai\backend
.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

## 快速启动客户端

```powershell
cd D:\JCC\jcc-s17-ai\client
npm run electron:dev
```

## Windows 打包

```powershell
cd D:\JCC\jcc-s17-ai\client
npm run dist:win
```

安装包输出目录：

```text
D:\JCC\jcc-s17-ai\client\dist-release
```

## 安全说明

本软件只做截图识别和推荐展示，不注入游戏、不读内存、不自动操作游戏。
