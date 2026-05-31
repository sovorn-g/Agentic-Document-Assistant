import glob
import os
from pathlib import Path

import config
import pymupdf.layout
import pymupdf4llm


os.environ["TOKENIZERS_PARALLELISM"] = "false"


def pdf_to_markdown(pdf_path, output_path):
    """Convert a PDF to Markdown.

    ``output_path`` may be either a target .md file or a directory. The written
    markdown path is returned.
    """
    pdf_path = Path(pdf_path)
    output_path = Path(output_path)
    if output_path.suffix.lower() != ".md":
        output_path = output_path / f"{pdf_path.stem}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(pdf_path)
    try:
        md = pymupdf4llm.to_markdown(
            doc,
            header=False,
            footer=False,
            page_separators=True,
            ignore_images=True,
            write_images=False,
            image_path=None,
        )
    finally:
        doc.close()

    md_cleaned = md.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="ignore")
    output_path.write_bytes(md_cleaned.encode("utf-8"))
    return output_path


def pdfs_to_markdowns(path_pattern, overwrite: bool = False):
    output_dir = Path(config.MARKDOWN_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    for pdf_path in map(Path, glob.glob(path_pattern)):
        md_path = (output_dir / pdf_path.stem).with_suffix(".md")
        if overwrite or not md_path.exists():
            pdf_to_markdown(pdf_path, output_dir)
