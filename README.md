# 股票分析适配器插件

这是一个为Astrbot设计的DailyStockAnalysis适配器插件，可以接收DailyStockAnalysis的股票分析HTML报告，并通过Astrbot将其发送给指定的群组或用户。

## 功能特性

- ✅ 接收HTTP Webhook请求
- ✅ 支持请求签名验证
- ✅ HTML内容渲染为图片
- ✅ 发送消息到指定群组和用户
- ✅ 可配置的安全设置

## 安装方式

1. 将整个插件文件夹复制到Astrbot的`data/plugins/`目录下
2. 重启Astrbot
3. 配置参数

## 配置说明

在Astrbot的WEB UI中进行配置


## 注意事项

1. 确保配置的端口没有被其他服务占用
2. 建议在生产环境中启用签名验证
3. HTML渲染功能依赖Astrbot的HTML渲染器
4. 目标群组和用户ID需要根据实际使用的平台获取

## 支持

如有问题，请提交Issue或联系开发者。
