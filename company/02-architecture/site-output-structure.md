# 站点输出结构

## 1. 第一阶段目标结构

建议本地生成如下结构：

```text
/follow/
├── index.html
├── archive/
│   └── index.html
└── daily/
    ├── YYYY-MM-DD.html
    └── ...
```

## 2. 页面职责

- `index.html`: 最近日报入口
- `archive/index.html`: 按日期归档
- `daily/*.html`: 单日报页面

## 3. 后续扩展

后续可以增加：

- 来源视图
- 主题视图
- 周报/月报页面
