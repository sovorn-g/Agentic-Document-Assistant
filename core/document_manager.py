from pathlib import Path
import shutil
import uuid

from utils.files import clear_directory_contents
from utils.pdf import pdf_to_markdown


class DocumentManager:
    SUPPORTED_SUFFIXES = {".pdf", ".md", ".markdown"}

    def __init__(self, rag_system):
        self.rag_system = rag_system
        self.store = rag_system.store

    @staticmethod
    def _safe_name(name: str) -> str:
        return "".join(c if c.isalnum() or c in "._- " else "_" for c in name).strip() or "document"

    @staticmethod
    def _path_from_upload(path_or_file) -> Path:
        if isinstance(path_or_file, Path):
            return path_or_file
        if isinstance(path_or_file, str):
            return Path(path_or_file)
        if isinstance(path_or_file, dict):
            return Path(path_or_file.get("path") or path_or_file.get("name") or "")
        return Path(getattr(path_or_file, "path", None) or getattr(path_or_file, "name", None) or str(path_or_file or ""))

    @classmethod
    def is_supported_file(cls, path_or_name) -> bool:
        return cls._path_from_upload(path_or_name).suffix.lower() in cls.SUPPORTED_SUFFIXES

    def add_documents(self, project_id, document_paths, progress_callback=None):
        if not project_id or not document_paths:
            return 0, 0

        if isinstance(document_paths, (str, Path, dict)) or not hasattr(document_paths, "__iter__"):
            document_paths = [document_paths]
        document_paths = [self._path_from_upload(p) for p in document_paths if p and self.is_supported_file(p)]

        if not document_paths:
            return 0, 0

        markdown_dir = self.rag_system.get_project_markdown_dir(project_id)
        originals_dir = self.rag_system.get_project_originals_dir(project_id)
        parent_store = self.rag_system.get_parent_store(project_id)
        collection = self.rag_system.vector_db.get_collection(self.rag_system.collection_name)

        added = 0
        skipped = 0

        for i, doc_path in enumerate(document_paths):
            source_path = Path(doc_path)
            filename = self._safe_name(source_path.name)
            if progress_callback:
                progress_callback((i + 1) / len(document_paths), f"Processing {filename}")

            existing_document = self.store.find_active_document_by_filename(project_id, filename)
            document_id = str(uuid.uuid4())
            original_path = originals_dir / f"{document_id}_{filename}"
            markdown_path = markdown_dir / f"{document_id}_{source_path.stem}.md"

            try:
                shutil.copy(source_path, original_path)
                if source_path.suffix.lower() in {".md", ".markdown"}:
                    shutil.copy(source_path, markdown_path)
                else:
                    pdf_to_markdown(source_path, markdown_path)

                parent_chunks, child_chunks = self.rag_system.chunker.create_chunks_single(
                    markdown_path,
                    project_id=project_id,
                    document_id=document_id,
                    source_name=filename,
                )

                if not child_chunks:
                    original_path.unlink(missing_ok=True)
                    markdown_path.unlink(missing_ok=True)
                    skipped += 1
                    continue

                collection.add_documents(child_chunks)
                parent_store.save_many(parent_chunks)
                self.store.add_document(
                    project_id=project_id,
                    document_id=document_id,
                    filename=filename,
                    original_path=str(original_path),
                    markdown_path=str(markdown_path),
                )
                if existing_document:
                    self.delete_document(existing_document["id"])
                added += 1

            except Exception as e:
                print(f"Error processing {doc_path}: {e}")
                original_path.unlink(missing_ok=True)
                markdown_path.unlink(missing_ok=True)
                parent_store.delete_document(document_id)
                self.rag_system.vector_db.delete_by_metadata(
                    self.rag_system.collection_name,
                    document_id=document_id,
                )
                skipped += 1

        if added:
            self.rag_system.invalidate_project_resources(project_id)

        return added, skipped

    def list_documents(self, project_id):
        if not project_id:
            return []
        return self.store.list_documents(project_id)

    def delete_document(self, document_id):
        document = self.store.get_document(document_id)
        if not document:
            return False

        if document["original_path"]:
            Path(document["original_path"]).unlink(missing_ok=True)
        Path(document["markdown_path"]).unlink(missing_ok=True)
        self.rag_system.get_parent_store(document["project_id"]).delete_document(document_id)
        self.rag_system.vector_db.delete_by_metadata(
            self.rag_system.collection_name,
            document_id=document_id,
        )
        self.store.mark_document_deleted(document_id)
        self.rag_system.invalidate_project_resources(document["project_id"])
        return True

    def clear_project(self, project_id):
        if not project_id:
            return

        project_dir = self.rag_system.get_project_storage_dir(project_id)
        clear_directory_contents(project_dir)
        self.rag_system.get_project_markdown_dir(project_id)
        self.rag_system.get_project_originals_dir(project_id)
        self.rag_system.get_parent_store(project_id)
        self.rag_system.vector_db.delete_by_metadata(
            self.rag_system.collection_name,
            project_id=project_id,
        )
        self.store.mark_project_documents_deleted(project_id)
        self.rag_system.invalidate_project_resources(project_id)
