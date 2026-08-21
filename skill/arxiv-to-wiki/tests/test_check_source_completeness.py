import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_source_completeness.py"
SPEC = importlib.util.spec_from_file_location("check_source_completeness", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def detailed_text(seed: str, minimum: int) -> str:
    return (seed * ((minimum // len(seed)) + 2))[: minimum + 10]


class SourceCompletenessTests(unittest.TestCase):
    def write_note(self, root: Path, *, thin: bool) -> Path:
        source_dir = root / "wiki" / "sources"
        source_dir.mkdir(parents=True)
        motivation = "很重要。" if thin else detailed_text("视觉遮挡使机器人无法判断接触变化，", 70)
        gap = "还不够。" if thin else detailed_text("已有方法缺少高频闭环与跨模态对齐，", 70)
        overview = "使用模型。" if thin else detailed_text("方法先学习视觉规划，再通过触觉反馈连续修正动作，", 90)
        core = "两个模块。" if thin else detailed_text("核心机制缓存视觉上下文并让快速专家完成动作去噪，", 90)
        breakdown = "- 一个步骤。" if thin else "- 编码多帧触觉。\n- 缓存视觉上下文。\n- 高频修正动作。"
        takeaways = "- 有效。" if thin else "- 视觉负责规划。\n- 触觉负责快速纠偏。"
        body = f"""---
source_type: paper
source_url: https://arxiv.org/abs/1234.56789
date: 2026-01-01
domains: [robotics]
tags: [vla]
related_topics: [robotics]
status: analyzed
hero_image: https://arxiv.org/html/1234.56789/overview.png
---

# Example

## 太长不看
这是论文结论。

## 直观理解
这是直观解释。

![架构总览](https://arxiv.org/html/1234.56789/overview.png)

## 核心信息
这是核心信息。

## 背景与问题

**动机：** {motivation}

**问题缺口：** {gap}

## 论文摘要（英文原文）
An English abstract.

## 论文摘要（中文翻译）
中文摘要。

## 方法

**方法概述：** {overview}

**核心机制：** {core}

**方法拆解：**
{breakdown}

**关键要点：**
{takeaways}

## 结果
具体结果。

## 洞察
具体洞察。

## 风险与判断

**局限：**
- 单一平台验证。

**适用场景：**
- 接触丰富的任务。

**最终判断：**
- 值得继续跟踪。

## 相关主题
- robotics
"""
        path = source_dir / "example.md"
        path.write_text(body, encoding="utf-8")
        return path

    def test_rejects_thin_background_and_method_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            errors, _ = MODULE.check_markdown(self.write_note(Path(tmp), thin=True))

        self.assertTrue(any("backgroundMotivation" in error for error in errors))
        self.assertTrue(any("backgroundGap" in error for error in errors))
        self.assertTrue(any("methodOverview" in error for error in errors))
        self.assertTrue(any("methodCore" in error for error in errors))
        self.assertTrue(any("methodBreakdown" in error for error in errors))
        self.assertTrue(any("methodTakeaways" in error for error in errors))

    def test_accepts_detailed_structured_background_and_method(self):
        with tempfile.TemporaryDirectory() as tmp:
            errors, _ = MODULE.check_markdown(self.write_note(Path(tmp), thin=False))

        self.assertEqual(errors, [])

    def test_accepts_heading_structured_background_and_method(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_note(Path(tmp), thin=False)
            text = path.read_text(encoding="utf-8")
            for label in ["动机", "问题缺口", "方法概述", "核心机制", "方法拆解", "关键要点"]:
                text = re.sub(
                    rf"^\*\*{label}：\*\*\s*(.*)$",
                    rf"### {label}\n\n\1",
                    text,
                    flags=re.MULTILINE,
                )
            path.write_text(text, encoding="utf-8")

            errors, _ = MODULE.check_markdown(path)

        self.assertEqual(errors, [])

    def test_package_check_rejects_missing_structured_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_dir = Path(tmp)
            source_dir = package_dir / "source"
            source_dir.mkdir()
            payload = {
                "tldr": "结论",
                "method": "方法",
                "risks": "风险",
                "sourceUrl": "https://arxiv.org/abs/1234.56789",
                "riskLimitations": ["限制"],
                "riskScenarios": ["场景"],
                "riskJudgment": ["判断"],
            }
            (source_dir / "example.json").write_text(json.dumps(payload), encoding="utf-8")

            errors, _ = MODULE.check_package_json(package_dir, "example")

        self.assertTrue(any("backgroundMotivation" in error for error in errors))
        self.assertTrue(any("methodOverview" in error for error in errors))
        self.assertTrue(any("methodBreakdown" in error for error in errors))

    def test_rejects_figure_without_explicit_hero(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_note(Path(tmp), thin=False)
            text = path.read_text(encoding="utf-8").replace(
                "hero_image: https://arxiv.org/html/1234.56789/overview.png\n",
                "",
            )
            path.write_text(text, encoding="utf-8")

            errors, _ = MODULE.check_markdown(path)

        self.assertIn("note contains figures but frontmatter is missing hero_image", errors)

    def test_package_rejects_figure_gallery_without_hero(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_dir = Path(tmp)
            source_dir = package_dir / "source"
            source_dir.mkdir()
            payload = {
                "tldr": "结论",
                "method": "方法",
                "risks": "风险",
                "sourceUrl": "https://arxiv.org/abs/1234.56789",
                "riskLimitations": ["限制"],
                "riskScenarios": ["场景"],
                "riskJudgment": ["判断"],
                "backgroundMotivation": detailed_text("动机", 70),
                "backgroundGap": detailed_text("缺口", 70),
                "methodOverview": detailed_text("概述", 90),
                "methodCore": detailed_text("机制", 90),
                "methodBreakdown": ["步骤一", "步骤二", "步骤三"],
                "methodTakeaways": ["要点一", "要点二"],
                "figureGallery": [{"src": "https://example.com/overview.png"}],
                "heroImage": "",
            }
            (source_dir / "example.json").write_text(json.dumps(payload), encoding="utf-8")

            errors, _ = MODULE.check_package_json(package_dir, "example")

        self.assertIn("package JSON has figureGallery but missing heroImage", errors)


if __name__ == "__main__":
    unittest.main()
