# 第三方来源与许可说明

## 上游项目

- 项目：FlapPearLabs/xuetangx-complete
- 仓库：https://github.com/FlapPearLabs/xuetangx-complete
- 本地改造基线：`1c440c264315c6daea9d820e1f6b1d19ed78a1db`
- 固定版本来源：https://github.com/FlapPearLabs/xuetangx-complete/tree/1c440c264315c6daea9d820e1f6b1d19ed78a1db
- 许可声明来源：https://github.com/FlapPearLabs/xuetangx-complete/blob/1c440c264315c6daea9d820e1f6b1d19ed78a1db/README.md

上游该版本 README 包含 MIT 许可证徽章，并在“许可证”一节声明“MIT”。该版本文件树中没有独立的 LICENSE 文件。这里如实保留上游的许可声明及来源，不替原作者补造版权年份或权利人身份。沿用代码的著作权仍属于其原权利人。

## 沿用范围与本地修改

公开版本中的 `scripts/extract_course.py` 沿用上游对应文件，包括本地 Chrome 调试端口扫描、连接信息查询、课程信息提取、登录检查和视频信息读取。本地修改了 Cookie 读取方法：将 `page.cookies` 改为 `page.context.cookies('https://www.xuetangx.com')`，并清理了行尾空白。

公开版本中的 `requirements.txt` 延续上游的 Playwright 依赖声明。项目开发参考了上游的课程页面结构与使用方式；公开版本不包含旧版心跳注入、强制标记完成和复制评论脚本。

本项目另行实现目录工作流、状态记录与恢复、DSH 请求和响应校验、作业填写与提交、页面检查、验证码人工处理提醒、运行时限选择，以及相应测试、Windows 启动入口和使用文档。上述新增贡献的声明不覆盖上游已有代码，也不表示整个项目均由当前维护者独立原创。

## 分享与再分发

本项目新增贡献按根目录 `LICENSE` 中的 MIT 条款发布。上游的 MIT 许可声明按上述固定版本 README 保留。复制或再分发本项目时，应一并保留 `LICENSE`、本说明和源文件中已有的版权、许可声明。

第三方依赖（如 Playwright）仍适用其各自的许可证，本项目的许可声明不替代这些依赖的许可。
