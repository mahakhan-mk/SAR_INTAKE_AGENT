from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
from io import BytesIO
from pathlib import Path
import re
from typing import Any
from uuid import UUID
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

import yaml

from app.application.models import ReportPreviewResult

DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
IMAGE_RELATIONSHIP_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
EMU_PER_INCH = 914400
DEFAULT_IMAGE_DPI = 96
MAX_ARCHITECTURE_IMAGE_WIDTH_INCHES = 6.2
JINJA_EXPRESSION_PATTERN = re.compile(r"{{\s*(.*?)\s*}}")
LOOP_PATTERN = re.compile(r"{%\s*for\s+item\s+in\s+([a-zA-Z0-9_]+)\s*%}")
DEFAULT_FILTER_PATTERN = re.compile(r"""default\((?P<value>.+?),\s*true\)""")


@dataclass(frozen=True)
class RenderedInitialSarReport:
    bytes: bytes
    original_filename: str
    content_type: str
    file_size_bytes: int
    sha256: str


class InitialSarReportRenderer:
    def __init__(
        self,
        *,
        template_path: Path | None = None,
        mapping_path: Path | None = None,
    ) -> None:
        self.template_path = template_path or self._resolve_asset_path("initial_sar_report.docx")
        self.mapping_path = mapping_path or self._resolve_asset_path("report_template_mapping.yaml")
        with self.mapping_path.open("r", encoding="utf-8") as mapping_file:
            self.mapping = yaml.safe_load(mapping_file)

    def render(
        self,
        preview: ReportPreviewResult,
        *,
        architecture_image_bytes: bytes | None = None,
    ) -> RenderedInitialSarReport:
        context = self._build_context(preview)
        image_info = self._build_image_info(architecture_image_bytes)

        rendered_docx = self._render_docx(context, image_info)
        original_filename = f"initial-sar-report-{self._coerce_uuid(preview.assessmentId)}.docx"

        return RenderedInitialSarReport(
            bytes=rendered_docx,
            original_filename=original_filename,
            content_type=DOCX_CONTENT_TYPE,
            file_size_bytes=len(rendered_docx),
            sha256=hashlib.sha256(rendered_docx).hexdigest(),
        )

    def _render_docx(self, context: dict[str, object], image_info: _InlineImageInfo | None) -> bytes:
        with ZipFile(self.template_path) as template_zip:
            file_map = {name: template_zip.read(name) for name in template_zip.namelist()}

        document_xml = file_map["word/document.xml"].decode("utf-8")
        document_xml = self._render_repeatable_rows(document_xml, context)
        document_xml = self._render_repeatable_blocks(document_xml, context)
        document_xml = self._render_scalars(document_xml, context, image_info)

        document_relationships_xml = file_map["word/_rels/document.xml.rels"].decode("utf-8")
        content_types_xml = file_map["[Content_Types].xml"].decode("utf-8")

        if image_info is not None:
            relationship_id = self._next_relationship_id(document_relationships_xml)
            document_xml = self._inject_inline_image(document_xml, relationship_id, image_info)
            document_relationships_xml = self._append_relationship(
                document_relationships_xml,
                relationship_id,
                f"media/{image_info.filename}",
            )
            content_types_xml = self._ensure_image_content_type(content_types_xml, image_info.extension)
            file_map[f"word/media/{image_info.filename}"] = image_info.bytes
        else:
            document_xml = self._inject_inline_image(document_xml, None, None)

        file_map["word/document.xml"] = document_xml.encode("utf-8")
        file_map["word/_rels/document.xml.rels"] = document_relationships_xml.encode("utf-8")
        file_map["[Content_Types].xml"] = content_types_xml.encode("utf-8")

        output = BytesIO()
        with ZipFile(output, "w", ZIP_DEFLATED) as rendered_zip:
            for name, data in file_map.items():
                rendered_zip.writestr(name, data)
        return output.getvalue()

    def _build_context(self, preview: ReportPreviewResult) -> dict[str, object]:
        context_config: dict[str, str] = self.mapping.get("context", {})
        context: dict[str, object] = {}
        for context_key, source_path in context_config.items():
            if source_path == "runtime-resolved-inline-image":
                context[context_key] = "__INLINE_IMAGE__"
                continue
            if self._is_literal_mapping_value(source_path):
                context[context_key] = source_path
                continue
            context[context_key] = self._normalize_context_value(
                context_key,
                self._resolve_path(preview, source_path),
            )
        return context

    def _normalize_context_value(self, context_key: str, value: object | None) -> object | None:
        if context_key == "top_risk_drivers":
            return [self._normalize_top_risk_driver(item) for item in self._coerce_list(value)]
        if context_key == "checklist_items":
            return [self._normalize_checklist_item(item) for item in self._coerce_list(value)]
        if context_key == "vendor_reputation_rows":
            return [self._normalize_vendor_reputation_row(item) for item in self._coerce_list(value)]
        if context_key == "limitations":
            return [self._normalize_limitation(item) for item in self._coerce_list(value)]
        return value

    def _render_repeatable_rows(self, document_xml: str, context: dict[str, object]) -> str:
        row_pattern = re.compile(r"<w:tr\b.*?</w:tr>", re.DOTALL)

        def replace_row(match: re.Match[str]) -> str:
            row_xml = match.group(0)
            loop_match = LOOP_PATTERN.search(row_xml)
            if loop_match is None:
                return row_xml

            loop_name = loop_match.group(1)
            items = context.get(loop_name)
            rows = self._coerce_list(items)
            clean_row_xml = re.sub(r"{%\s*for\s+item\s+in\s+[a-zA-Z0-9_]+\s*%}", "", row_xml)
            clean_row_xml = re.sub(r"{%\s*endfor\s*%}", "", clean_row_xml)

            if rows:
                return "".join(self._render_loop_row(clean_row_xml, item) for item in rows)

            empty_message = (
                self.mapping.get("empty_list_behavior", {}).get(loop_name)
                or self.mapping.get("null_display")
                or ""
            )
            return self._render_empty_loop_row(clean_row_xml, empty_message)

        return row_pattern.sub(replace_row, document_xml)

    def _render_repeatable_blocks(self, document_xml: str, context: dict[str, object]) -> str:
        block_pattern = re.compile(
            r"<w:p\b[^>]*>(?:(?!</w:p>).)*?<w:t[^>]*>{%\s*for\s+item\s+in\s+([a-zA-Z0-9_]+)\s*%}</w:t>"
            r"(?:(?!</w:p>).)*?</w:p>"
            r"(?P<body>.*?)"
            r"<w:p\b[^>]*>(?:(?!</w:p>).)*?<w:t[^>]*>{%\s*endfor\s*%}</w:t>(?:(?!</w:p>).)*?</w:p>",
            re.DOTALL,
        )

        def replace_block(match: re.Match[str]) -> str:
            loop_name = match.group(1)
            block_body = match.group("body")
            rows = self._coerce_list(context.get(loop_name))
            if rows:
                return "".join(self._render_loop_row(block_body, item) for item in rows)

            empty_message = (
                self.mapping.get("empty_list_behavior", {}).get(loop_name)
                or self.mapping.get("null_display")
                or ""
            )
            return self._render_empty_loop_row(block_body, empty_message)

        return block_pattern.sub(replace_block, document_xml)

    def _render_loop_row(self, row_xml: str, item: object) -> str:
        def replace_expression(match: re.Match[str]) -> str:
            expression = match.group(1).strip()
            if not expression.startswith("item."):
                return match.group(0)
            value = self._evaluate_loop_expression(expression, item)
            return escape(self._stringify(value))

        return JINJA_EXPRESSION_PATTERN.sub(replace_expression, row_xml)

    def _render_empty_loop_row(self, row_xml: str, empty_message: str) -> str:
        replacements = 0

        def replace_expression(match: re.Match[str]) -> str:
            nonlocal replacements
            expression = match.group(1).strip()
            if not expression.startswith("item."):
                return match.group(0)
            replacements += 1
            return escape(empty_message if replacements == 1 else "")

        return JINJA_EXPRESSION_PATTERN.sub(replace_expression, row_xml)

    def _render_scalars(
        self,
        document_xml: str,
        context: dict[str, object],
        image_info: _InlineImageInfo | None,
    ) -> str:
        def replace_expression(match: re.Match[str]) -> str:
            expression = match.group(1).strip()
            value = self._evaluate_scalar_expression(expression, context)
            if expression == "architecture_diagram" and image_info is None:
                return ""
            return escape(self._stringify(value))

        return JINJA_EXPRESSION_PATTERN.sub(replace_expression, document_xml)

    def _inject_inline_image(
        self,
        document_xml: str,
        relationship_id: str | None,
        image_info: _InlineImageInfo | None,
    ) -> str:
        sentinel_run_pattern = re.compile(
            r"<w:r\b[^>]*>.*?<w:t[^>]*>__INLINE_IMAGE__</w:t>.*?</w:r>",
            re.DOTALL,
        )
        if image_info is None or relationship_id is None:
            return sentinel_run_pattern.sub('<w:r><w:t xml:space="preserve"></w:t></w:r>', document_xml, count=1)
        return sentinel_run_pattern.sub(
            self._build_inline_image_run_xml(relationship_id, image_info),
            document_xml,
            count=1,
        )

    def _evaluate_scalar_expression(self, expression: str, context: dict[str, object]) -> object:
        variable_name, default_value = self._split_expression(expression)
        value = context.get(variable_name)
        if self._is_missing(value):
            return default_value
        return value

    def _evaluate_loop_expression(self, expression: str, item: object) -> object:
        item_expression, default_value = self._split_expression(expression)
        item_path = item_expression.split(".", 1)[1]
        value = self._resolve_path(item, item_path)
        if self._is_missing(value):
            if default_value == "__SELF__":
                return item
            return default_value
        return value

    def _split_expression(self, expression: str) -> tuple[str, object]:
        if "|" not in expression:
            return expression.strip(), self.mapping.get("null_display", "")

        variable_name, filters = expression.split("|", 1)
        default_match = DEFAULT_FILTER_PATTERN.search(filters)
        if default_match is None:
            return variable_name.strip(), self.mapping.get("null_display", "")

        raw_default = default_match.group("value").strip()
        if raw_default == "item":
            default_value: object = "__SELF__"
        elif (raw_default.startswith('"') and raw_default.endswith('"')) or (
            raw_default.startswith("'") and raw_default.endswith("'")
        ):
            default_value = raw_default[1:-1]
        else:
            default_value = raw_default
        return variable_name.strip(), default_value

    def _resolve_path(self, value: object | None, path: str) -> object | None:
        current = value
        segments = path.split(".")
        for index, segment in enumerate(segments):
            if current is None:
                return None

            if isinstance(current, dict) and segment in current:
                current = current[segment]
                continue

            if hasattr(current, segment):
                current = getattr(current, segment)
                continue

            remaining_path = ".".join(segments[index + 1 :])
            if remaining_path:
                fallback = self._resolve_path(current, remaining_path)
                if fallback is not None:
                    return fallback

            if "." not in segment:
                camel_case_segment = self._to_camel_case(segment)
                if hasattr(current, camel_case_segment):
                    current = getattr(current, camel_case_segment)
                    continue
                if isinstance(current, dict) and camel_case_segment in current:
                    current = current[camel_case_segment]
                    continue

            return None
        return current

    def _normalize_top_risk_driver(self, item: object) -> dict[str, object]:
        return {
            "domain": self._resolve_path(item, "domain"),
            "risk_level": self._resolve_path(item, "risk_level") or self._resolve_path(item, "level"),
            "question": self._resolve_path(item, "question"),
            "response": self._resolve_path(item, "response"),
            "reason": self._resolve_path(item, "reason"),
        }

    def _normalize_checklist_item(self, item: object) -> dict[str, object]:
        return {
            "document_type": self._resolve_path(item, "document_type") or self._resolve_path(item, "documentType"),
            "verdict": (
                self._resolve_path(item, "verdict")
                or self._resolve_path(item, "effectiveVerdict")
                or self._resolve_path(item, "effective_verdict")
            ),
            "file_status": (
                self._resolve_path(item, "file_status")
                or self._resolve_path(item, "detectedFileStatus")
                or self._resolve_path(item, "detected_file_status")
            ),
            "filename": self._resolve_path(item, "filename"),
            "review_reason": (
                self._resolve_path(item, "review_reason")
                or self._resolve_path(item, "reviewerReason")
                or self._resolve_path(item, "reviewer_reason")
            ),
        }

    def _normalize_vendor_reputation_row(self, item: object) -> dict[str, object]:
        return {
            "category": self._resolve_path(item, "category"),
            "sentiment": self._resolve_path(item, "sentiment"),
            "interpretation": self._resolve_path(item, "interpretation"),
            "risk_impact": self._resolve_path(item, "risk_impact") or self._resolve_path(item, "riskImpact"),
            "confidence": self._resolve_path(item, "confidence"),
            "sources": self._resolve_path(item, "sources"),
        }

    def _normalize_limitation(self, item: object) -> dict[str, object]:
        if isinstance(item, dict):
            return {"text": self._resolve_path(item, "text") or item}
        return {"text": item}

    def _build_image_info(self, architecture_image_bytes: bytes | None) -> _InlineImageInfo | None:
        if architecture_image_bytes is None:
            return None

        extension, mime_type, width_px, height_px = self._parse_image_metadata(architecture_image_bytes)
        max_width_emu = int(MAX_ARCHITECTURE_IMAGE_WIDTH_INCHES * EMU_PER_INCH)
        width_emu = int(width_px / DEFAULT_IMAGE_DPI * EMU_PER_INCH)
        height_emu = int(height_px / DEFAULT_IMAGE_DPI * EMU_PER_INCH)
        if width_emu > max_width_emu:
            scale = max_width_emu / width_emu
            width_emu = max_width_emu
            height_emu = max(1, int(height_emu * scale))

        return _InlineImageInfo(
            bytes=architecture_image_bytes,
            extension=extension,
            mime_type=mime_type,
            filename=f"architecture_diagram.{extension}",
            width_emu=width_emu,
            height_emu=height_emu,
        )

    def _parse_image_metadata(self, image_bytes: bytes) -> tuple[str, str, int, int]:
        if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            width = int.from_bytes(image_bytes[16:20], "big")
            height = int.from_bytes(image_bytes[20:24], "big")
            return "png", "image/png", width, height

        if image_bytes.startswith(b"\xff\xd8"):
            index = 2
            while index < len(image_bytes):
                if image_bytes[index] != 0xFF:
                    index += 1
                    continue
                marker = image_bytes[index + 1]
                index += 2
                if marker in {0xD8, 0xD9}:
                    continue
                segment_length = int.from_bytes(image_bytes[index : index + 2], "big")
                if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                    height = int.from_bytes(image_bytes[index + 3 : index + 5], "big")
                    width = int.from_bytes(image_bytes[index + 5 : index + 7], "big")
                    return "jpeg", "image/jpeg", width, height
                index += segment_length

        raise ValueError("Architecture image bytes must be PNG or JPEG.")

    def _next_relationship_id(self, relationships_xml: str) -> str:
        relationship_ids = [int(value) for value in re.findall(r'Id="rId(\d+)"', relationships_xml)]
        return f"rId{max(relationship_ids, default=0) + 1}"

    def _append_relationship(self, relationships_xml: str, relationship_id: str, target: str) -> str:
        relationship_xml = (
            f'<Relationship Id="{relationship_id}" Type="{IMAGE_RELATIONSHIP_TYPE}" Target="{target}"/>'
        )
        return relationships_xml.replace("</Relationships>", f"{relationship_xml}</Relationships>")

    def _ensure_image_content_type(self, content_types_xml: str, extension: str) -> str:
        if f'Extension="{extension}"' in content_types_xml:
            return content_types_xml

        mime_type = "image/png" if extension == "png" else "image/jpeg"
        default_xml = f'<Default Extension="{extension}" ContentType="{mime_type}"/>'
        return content_types_xml.replace("</Types>", f"{default_xml}</Types>")

    def _build_inline_image_run_xml(self, relationship_id: str, image_info: _InlineImageInfo) -> str:
        return (
            "<w:r>"
            "<w:drawing xmlns:a=\"http://schemas.openxmlformats.org/drawingml/2006/main\" "
            "xmlns:pic=\"http://schemas.openxmlformats.org/drawingml/2006/picture\">"
            "<wp:inline distT=\"0\" distB=\"0\" distL=\"0\" distR=\"0\">"
            f"<wp:extent cx=\"{image_info.width_emu}\" cy=\"{image_info.height_emu}\"/>"
            "<wp:effectExtent l=\"0\" t=\"0\" r=\"0\" b=\"0\"/>"
            f"<wp:docPr id=\"1\" name=\"Architecture Diagram\" descr=\"{escape(image_info.filename)}\"/>"
            "<wp:cNvGraphicFramePr>"
            "<a:graphicFrameLocks noChangeAspect=\"1\"/>"
            "</wp:cNvGraphicFramePr>"
            "<a:graphic>"
            "<a:graphicData uri=\"http://schemas.openxmlformats.org/drawingml/2006/picture\">"
            "<pic:pic>"
            "<pic:nvPicPr>"
            f"<pic:cNvPr id=\"0\" name=\"{escape(image_info.filename)}\"/>"
            "<pic:cNvPicPr/>"
            "</pic:nvPicPr>"
            "<pic:blipFill>"
            f"<a:blip r:embed=\"{relationship_id}\"/>"
            "<a:stretch><a:fillRect/></a:stretch>"
            "</pic:blipFill>"
            "<pic:spPr>"
            "<a:xfrm>"
            "<a:off x=\"0\" y=\"0\"/>"
            f"<a:ext cx=\"{image_info.width_emu}\" cy=\"{image_info.height_emu}\"/>"
            "</a:xfrm>"
            "<a:prstGeom prst=\"rect\"><a:avLst/></a:prstGeom>"
            "</pic:spPr>"
            "</pic:pic>"
            "</a:graphicData>"
            "</a:graphic>"
            "</wp:inline>"
            "</w:drawing>"
            "</w:r>"
        )

    @staticmethod
    def _resolve_asset_path(filename: str) -> Path:
        project_root = Path(__file__).resolve().parents[2]
        candidate_paths = [
            project_root / "app" / "report_template" / filename,
            project_root / "app" / "report_templates" / filename,
        ]
        for candidate_path in candidate_paths:
            if candidate_path.exists():
                return candidate_path
        raise FileNotFoundError(f"Unable to locate report template asset: {filename}")

    @staticmethod
    def _is_literal_mapping_value(value: str) -> bool:
        return any(character.isspace() for character in value)

    @staticmethod
    def _to_camel_case(name: str) -> str:
        parts = name.split("_")
        return parts[0] + "".join(part.capitalize() for part in parts[1:])

    @staticmethod
    def _coerce_uuid(value: UUID | str) -> UUID:
        return value if isinstance(value, UUID) else UUID(str(value))

    @staticmethod
    def _coerce_list(value: object | None) -> list[object]:
        return list(value) if isinstance(value, list) else []

    @staticmethod
    def _is_missing(value: object | None) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return value == ""
        if isinstance(value, list):
            return len(value) == 0
        return False

    @staticmethod
    def _stringify(value: object | None) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.isoformat().replace("+00:00", "Z")
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, UUID):
            return str(value)
        return str(value)


@dataclass(frozen=True)
class _InlineImageInfo:
    bytes: bytes
    extension: str
    mime_type: str
    filename: str
    width_emu: int
    height_emu: int
