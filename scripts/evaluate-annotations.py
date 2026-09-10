import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.annotation_evaluator import (  # noqa: E402
    AnnotationEvaluationError,
    analyze_annotation_audio,
    evaluate_annotation_package,
    evaluate_synthetic_controls,
    save_evaluation,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="质检人工标注 CSV，并生成不含原始文本的开发集评测摘要。"
    )
    parser.add_argument("annotation_dir", type=Path, help="标注包目录")
    parser.add_argument(
        "--audio-dir",
        type=Path,
        help="可选的原始录音目录；提供后会实际运行 ASR 和 VAD",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "runtime" / "evaluation" / "latest",
        help="评测结果目录（默认写入 Git 忽略的 runtime/evaluation/latest）",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=PROJECT_ROOT / "runtime" / "evaluation" / "audio-cache",
        help="批量语音分析缓存目录",
    )
    parser.add_argument(
        "--synthetic-controls",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "evaluation"
        / "synthetic_content_controls.v1.json",
        help="AI 合成内容控制集；用于补充负例和规则回归，不替代人工标注",
    )
    args = parser.parse_args()

    try:
        system_analyses = None
        audio_issues = None
        if args.audio_dir:
            def progress(audio_id: str, index: int, total: int, cached: bool) -> None:
                state = "缓存" if cached else "分析"
                print(f"[{index}/{total}] {state} {audio_id}", flush=True)

            system_analyses, audio_issues = analyze_annotation_audio(
                args.annotation_dir,
                args.audio_dir,
                args.cache_dir,
                progress,
            )
        synthetic_controls = (
            evaluate_synthetic_controls(args.synthetic_controls)
            if args.synthetic_controls.is_file()
            else None
        )
        report = evaluate_annotation_package(
            args.annotation_dir,
            system_analyses=system_analyses,
            audio_issues=audio_issues,
            synthetic_controls=synthetic_controls,
        )
        json_path, markdown_path = save_evaluation(report, args.output_dir)
    except AnnotationEvaluationError as exc:
        print(f"评测失败：{exc}", file=sys.stderr)
        return 2

    source = report["source_summary"]
    alignment = report["content_score_alignment"]["corrected_transcript"][
        "content_total"
    ]
    print(
        f"完成：{source['evaluated_audio_count']} 条样本，"
        f"内容总分 MAE={alignment['mae']}，"
        f"数据状态={report['data_quality']['status']}"
    )
    print(f"JSON：{json_path.resolve()}")
    print(f"Markdown：{markdown_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
