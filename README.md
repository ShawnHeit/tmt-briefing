# TMT Briefing

公开版 TMT 行业研究简报。访问网址（GitHub Pages 启用后生效）：

https://shawnheit.github.io/tmt-briefing/

## 目录结构

```
.
├── index.html          主页面
├── 知识库/             被 index.html 引用的研报 PDF
├── publish.py          本地一键发布脚本
└── README.md
```

## 更新流程

```bash
# 仅同步内容到本目录（不推送）
python3 publish.py

# 同步 + 自动 git commit & push
python3 publish.py --push
```

`publish.py` 会：

1. 从 `~/Documents/TMT_Bot/Bot/tmt-briefing/tmt-briefing.html` 读取最新简报
2. 扫描 HTML 里引用的 PDF，只复制这些 PDF 到本仓库
3. 把 HTML 里的相对路径从 `../知识库/` 改写成 `知识库/`
4. 自动清理本仓库里不再被引用的旧 PDF
5. （可选）自动提交并推送
