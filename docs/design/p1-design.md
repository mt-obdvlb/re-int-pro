# P1 工作台设计与实现依据

2026-09-06，使用用户指定的 Build Web Apps、design-taste-frontend 和 frontend-skill。
工作台采用 App 规则；taste 的 landing-page 规则不适用密集工具界面。

## 视觉锚点

[Image Gen 原始概念图](p1-workspace-concept.png)，原生尺寸 1536×1024。
生成要求：ProbeOps 中文开发者工作台，左导航、中央运行列表与时间线、右侧任务上下文；浅灰冷色底、青绿色强调、真实表格和控件；禁止营销英雄区、渐变、装饰图、卡片拼贴。示例运行仅用于视觉设计。
单一 Agent 独立实施，未调用百炼。

## Tokens 与组件

- 字体：Geist 本地打包；中文使用系统苹方/微软雅黑。正文 14–16px，页面标题 30px，表格 14px，ID 使用系统等宽。
- 布局：桌面侧栏 232px，顶栏 64px，内容边距 28px，右侧 280px。主工作区开放布局和分隔线，不加卡片外壳。
- 色彩：canvas `#f7f8fa`，sidebar `#f0f2f4`，ink `#202629`，muted `#667078`，border `#e0e5e7`，accent `#087f72`。
- 间距以 4/8px 递增；表单控件圆角 6px；表格行高 48px。
- Phosphor 线性图标：Pulse、ClockCounterClockwise、BookOpen、Flask、Sun/Moon、Plus、CaretRight、CheckCircle、Prohibit。
- 组件：Shell、Workspace、RunTable、RunDetail、CreateRunDialog、Inspector、ErrorNotice。
- 动效 3：按钮反馈、选中反馈、轻量进入；尊重减少动态效果。无 GSAP/Motion 依赖。
- 深色主题保留层级与唯一强调色；移动端导航横排、上下文改为底部区域，表格局部横向滚动。

## 必要功能差异

概念图展示 3 条示例记录；实际启动为空，只有用户提交后由真实后端产生记录。
实际 ID、UTC 转换的本地时间与事件条数依据数据库，不能为了截图伪造。
增加新建弹窗、取消按钮、错误/空态、加载状态、分页、连接状态、主题切换与使用说明，属于工作流需要。
取消/失败不显示完成报告；P1 所有诊断报告明确“无法确定根因”。
概念图中的 820ms 只出现在明确标识的模拟观测中。

最终截图、1536×1024原生视口逐项对照和交互结果见 [P1验收记录](../p1-validation.md)。移动截图390×844；浏览器高层截图缩小问题通过同一IAB页面的CDP截图解决，未修改实际界面数据。
