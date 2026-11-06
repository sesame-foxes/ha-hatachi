# ha-hatachi - 海信日立中央空调 Home Assistant 集成

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

## 写在前面
该集成frok自https://github.com/kiwiwiki007/ha-hatachi
由于我需要在ha中控制地暖，而原集成不支持，在ai的帮助下添加了地暖的控制功能，自行试用通过。
![alt text](picture.png)

## 使用建议
由于日立智家不支持同时登录，该插件会导致app掉线。建议注册两个日立智家账号，并拉入同一家庭。ha和手机端分别登录。


# 原描述

Home Assistant 自定义集成，用于控制**海信日立 (Hisense Hitachi) 中央空调**，通过海信日立云 API 实现远程控制。

支持标准空调、特殊机型以及**新风系统**。

---

## 功能特性

- ✅ UI 配置流程（Config Flow），手机号 + 密码登录
- ✅ 自动发现账户下所有家庭和内机设备
- ✅ 开/关、温度设置、模式切换、风速控制
- ✅ 标准空调模式：制冷、制热、除湿、送风
- ✅ **新风系统专用支持**（仅风速控制）
- ✅ 每 10 秒自动轮询状态
- ✅ Token 自动刷新（每 24 小时）
- ✅ 中英文翻译

## 安装方式

### 方式一：HACS（推荐）

1. 确保已安装 [HACS](https://hacs.xyz/)
2. 在 HACS 中添加自定义仓库：`https://github.com/kiwiwiki007/ha-hatachi`
3. 类别选择「集成 (Integration)」
4. 搜索 "Hitachi AC" 并安装
5. 重启 Home Assistant

### 方式二：手动安装

```bash
# 进入 custom_components 目录
cd /path/to/your/homeassistant/config/custom_components

# 克隆仓库
git clone https://github.com/kiwiwiki007/ha-hatachi.git temp
mv temp/custom_components/ha_hatachi .
rm -rf temp
```

或直接下载并解压到 `custom_components/ha_hatachi/`。

## 配置

1. 重启 Home Assistant
2. 前往 **设置 → 设备与服务 → 添加集成**
3. 搜索 "Hitachi AC"
4. 输入海信日立 iEZ2 应用的登录信息：
   - **手机号**
   - **密码**
5. 提交后自动完成设备发现

## 支持的设备类型

| 类型 | 说明 | 功能 |
|------|------|------|
| 标准空调 (05) | 普通室内机 | 温度 + 模式 + 风速 |
| 特殊机型 (03) | 特殊室内机 | 温度 + 模式 + 风速 |
| 新风系统 (0D) | 全热交换器/新风 | 仅风速控制 |

## 最低要求

- Home Assistant **2024.1.0** 或更高版本
- 海信日立 iEZ2 账号（手机号注册）
- 设备已配网并连接至海信日立云

## 项目结构

```
custom_components/ha_hatachi/
├── __init__.py          # 集成入口
├── api.py               # 云 API 客户端
├── climate.py           # Climate 平台实体
├── config_flow.py       # UI 配置流程
├── const.py             # 常量定义
├── coordinator.py       # 数据协调器
├── manifest.json        # 组件清单
├── icon.png             # 图标
├── logo.png             # Logo
├── brand/               # 品牌资源
└── translations/        # 翻译文件
```

## 致谢

本项目通过逆向海信日立 iEZ2 Android 应用（版本 7.5.3）的 API 实现，感谢相关社区贡献者。

## 许可证

MIT License - 详见 [LICENSE](LICENSE)
