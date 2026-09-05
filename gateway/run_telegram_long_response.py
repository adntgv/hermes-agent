"""Telegram long-response HTML and visual-report delivery."""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import secrets
from typing import Optional
from urllib.parse import urlencode, urlparse

from gateway.config import Platform
from gateway.platforms.base import MessageEvent
from gateway.telegram_long_response_html import (
    build_artifact_paths,
    parse_visual_digest_plan,
    sanitize_rendered_markdown_html,
    write_long_response_html_file,
    write_visual_digest_html_file,
)
from gateway.visual_report_store import save_latest_report


logger = logging.getLogger("gateway.run")


class GatewayTelegramLongResponseMixin:
    """Render and optionally host long Telegram responses as HTML reports."""

    def _telegram_long_response_html_config(self) -> dict:
        from gateway.run import _load_gateway_config

        cfg = _load_gateway_config()
        telegram_cfg = cfg.get("telegram") if isinstance(cfg.get("telegram"), dict) else {}
        raw = telegram_cfg.get("long_response_html")
        raw = raw if isinstance(raw, dict) else {}
        visual_raw = raw.get("visual_digest")
        visual_raw = visual_raw if isinstance(visual_raw, dict) else {}
        hosting_raw = raw.get("hosting")
        hosting_raw = hosting_raw if isinstance(hosting_raw, dict) else {}
        return {
            "enabled": bool(raw.get("enabled", False)),
            "threshold_chars": int(raw.get("threshold_chars", 1400) or 1400),
            "threshold_lines": int(raw.get("threshold_lines", 18) or 18),
            "notice": str(raw.get("notice") or "Full response is attached as an HTML file."),
            "caption": str(raw.get("caption") or "Full response attached as HTML."),
            "visual_digest": {
                "enabled": bool(visual_raw.get("enabled", False)),
                "caption": str(visual_raw.get("caption") or "Visual digest attached as HTML."),
                "send_raw_html": bool(visual_raw.get("send_raw_html", True)),
                "link_text": str(visual_raw.get("link_text") or "Open visual report"),
            },
            "hosting": {
                "enabled": bool(hosting_raw.get("enabled", False)),
                "endpoint_url": str(hosting_raw.get("endpoint_url") or ""),
                "bucket": str(hosting_raw.get("bucket") or ""),
                "public_base_url": str(hosting_raw.get("public_base_url") or ""),
                "loader_url": str(hosting_raw.get("loader_url") or ""),
                "loader_version": str(hosting_raw.get("loader_version") or "1"),
                "key_prefix": str(hosting_raw.get("key_prefix") or "long-responses"),
                "access_key_env": str(hosting_raw.get("access_key_env") or "MINIO_REPORTS_ACCESS_KEY"),
                "secret_key_env": str(hosting_raw.get("secret_key_env") or "MINIO_REPORTS_SECRET_KEY"),
                "link_text": str(hosting_raw.get("link_text") or "Open full response"),
                "fallback_to_attachment": bool(hosting_raw.get("fallback_to_attachment", True)),
            },
        }

    def _response_requires_html_document(self, response: str, cfg: dict) -> bool:
        if not response or not cfg.get("enabled"):
            return False
        threshold_chars = max(1, int(cfg.get("threshold_chars") or 1400))
        threshold_lines = max(1, int(cfg.get("threshold_lines") or 18))
        return len(response) > threshold_chars or response.count("\n") + 1 > threshold_lines

    def _long_response_html_paths(
        self, event: MessageEvent, ts: Optional[str] = None
    ) -> tuple[str, str, str]:
        return build_artifact_paths(event, ts)

    def _write_long_response_html_file(
        self, response: str, event: MessageEvent, *, ts: Optional[str] = None
    ) -> str:
        return write_long_response_html_file(response, event, self._render_md_to_html, ts=ts)

    async def _host_long_response_html(self, file_path: str, hosting_cfg: dict) -> Optional[str]:
        def _upload() -> Optional[str]:
            endpoint_url = str(hosting_cfg.get("endpoint_url") or "").rstrip("/")
            bucket = str(hosting_cfg.get("bucket") or "").strip("/")
            public_base_url = str(hosting_cfg.get("public_base_url") or "").rstrip("/")
            if not public_base_url and endpoint_url and bucket:
                public_base_url = f"{endpoint_url}/{bucket}"
            parsed_public_url = urlparse(public_base_url)
            if (
                parsed_public_url.scheme != "https"
                or not parsed_public_url.netloc
                or parsed_public_url.username
                or parsed_public_url.password
                or parsed_public_url.query
                or parsed_public_url.fragment
            ):
                logger.warning(
                    "Telegram long-response hosting requires a valid credential-free HTTPS public_base_url"
                )
                return None

            loader_url = str(hosting_cfg.get("loader_url") or "").rstrip("/")
            loader_query = ""
            if loader_url:
                parsed_loader_url = urlparse(loader_url)
                if (
                    parsed_loader_url.scheme != "https"
                    or not parsed_loader_url.netloc
                    or parsed_loader_url.netloc != parsed_public_url.netloc
                    or parsed_loader_url.username
                    or parsed_loader_url.password
                    or parsed_loader_url.query
                    or parsed_loader_url.fragment
                ):
                    logger.warning(
                        "Telegram long-response loader_url must be a credential-free HTTPS URL "
                        "on the public report origin"
                    )
                    return None
                loader_version = str(hosting_cfg.get("loader_version") or "1")
                if not re.fullmatch(r"[A-Za-z0-9._-]{1,32}", loader_version):
                    logger.warning("Telegram long-response loader_version contains unsupported characters")
                    return None
                loader_query = urlencode({"v": loader_version})

            access_key_env = str(hosting_cfg.get("access_key_env") or "")
            secret_key_env = str(hosting_cfg.get("secret_key_env") or "")
            if not endpoint_url or not bucket or not access_key_env or not secret_key_env:
                logger.warning("Telegram long-response hosting storage configuration is incomplete")
                return None

            from agent.secret_scope import get_secret

            access_key = get_secret(access_key_env, "") or ""
            secret_key = get_secret(secret_key_env, "") or ""
            if not access_key or not secret_key:
                logger.warning("Telegram long-response hosting credentials are unavailable")
                return None
            try:
                from tools.lazy_deps import ensure as ensure_lazy_dependency

                ensure_lazy_dependency("platform.telegram.long_response_hosting", prompt=False)
                import boto3
                from botocore.client import Config
            except (ImportError, RuntimeError) as exc:
                logger.warning("Telegram long-response hosting requires boto3: %s", exc)
                return None

            prefix = str(hosting_cfg.get("key_prefix") or "long-responses").strip("/")
            object_key = f"{prefix}/{secrets.token_urlsafe(18)}/index.html"
            client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                config=Config(signature_version="s3v4"),
                region_name="us-east-1",
            )
            client.upload_file(
                file_path,
                bucket,
                object_key,
                ExtraArgs={
                    "ContentType": "text/html; charset=utf-8",
                    "CacheControl": "private, no-store",
                },
            )
            direct_url = f"{public_base_url}/{object_key}"
            if not loader_url:
                return direct_url
            target_fragment = urlencode({"path": urlparse(direct_url).path})
            return f"{loader_url}?{loader_query}#{target_fragment}"

        try:
            return await asyncio.to_thread(_upload)
        except Exception as exc:
            logger.warning("Telegram long-response hosting failed: %s", exc, exc_info=True)
            return None

    def _write_visual_digest_html_file(
        self, response: str, event: MessageEvent, *, plan: dict, ts: Optional[str] = None
    ) -> str:
        path = write_visual_digest_html_file(response, event, self._render_md_to_html, plan=plan, ts=ts)
        try:
            source = getattr(event, "source", None)
            platform = getattr(getattr(source, "platform", None), "value", getattr(source, "platform", ""))
            save_latest_report(
                plan,
                source_response=response,
                source_metadata={"artifact_path": path},
                event_metadata={
                    "platform": platform,
                    "chat_id": getattr(source, "chat_id", ""),
                    "thread_id": getattr(source, "thread_id", ""),
                    "topic": getattr(source, "chat_topic", ""),
                },
            )
        except Exception as exc:
            logger.warning("Failed to persist latest visual report: %s", exc, exc_info=True)
        return path

    def _build_visual_digest_planner_messages(
        self, event: MessageEvent, response: str
    ) -> list[dict[str, str]]:
        topic = str(getattr(event.source, "chat_topic", "") or "")
        platform = str(getattr(event.source.platform, "value", event.source.platform) or "")
        # Keep this lookup on gateway.run for compatibility with existing plugin/test patch points.
        from gateway.run import _load_visual_report_registry_manifest_for_prompt

        manifest = _load_visual_report_registry_manifest_for_prompt()
        registered_types = [entry["type"] for entry in manifest]
        output_shape = {
            "title": "short title",
            "summary": "1-2 sentence comprehension-first summary",
            "theme_hint": "briefing|decision|system|plan|comparison|timeline|report|explainer",
            "metrics": [{"label": "exact source metric label", "value": "exact source value"}],
            "blocks": [
                {
                    "type": "one registered component type from registry_manifest",
                    "title": "block title",
                    "component_specific_fields": (
                        "flatten fields from that component's dataShape directly here at block root"
                    ),
                }
            ],
        }
        system = (
            "You are Hermes Visual Planner. Treat HTML as a visual canvas, not a container for styled "
            "Markdown. Analyze the source meaning first: entities, time, dependencies, state, priority, "
            "quantities, ownership, blockers, and exact details. Then choose visual representations that "
            "expose those relationships. Do not default to hero + cards + checklist + full markdown. "
            "You may only select registered visual report component types from the provided registry "
            "manifest; never invent block types or use unregistered legacy helpers. Prefer gantt for work "
            "across time, kanban for state, priority_matrix for impact/urgency, dependency_graph for "
            "prerequisites, flow for procedures, progress for grounded completion values, comparison_table "
            "for tradeoffs, chart for explicit numeric series, and details for lossless drill-down. The "
            "first screen must provide insight unavailable from merely styling the original document. "
            "Preserve all operationally relevant details in visual labels or collapsible details; never "
            "invent facts, dates, percentages, effort, progress, or dependencies. Return JSON only, no "
            "prose and no code fences."
        )
        user = (
            f"Context: platform={platform}; topic={topic or 'none'}\n\n"
            "Create a visual artifact plan for the following assistant response.\n"
            "Constraints:\n"
            "- optimize for fast comprehension on iPhone; essential content must work without JavaScript\n"
            f"- only select registered visual report component types: {', '.join(registered_types)}\n"
            "- first identify what should be represented visually, then choose 3-7 complementary blocks\n"
            "- use at least two relationship-bearing visual blocks when the source contains time, state, "
            "dependencies, priority, or process\n"
            "- reserve details for supporting exact evidence, not as the primary representation unless the "
            "source is mostly reference text\n"
            "- use details sections to preserve exact tasks or evidence that would otherwise be lost\n"
            "- metrics and progress values must exist in the source; do not estimate them\n"
            "- every block must be grounded in the source response; omit unsupported axes or values\n"
            "- flatten component-specific fields at each block root according to the selected component's "
            "dataShape; do not nest them under payload, props, data, or config\n"
            "- do not repeat the same fact in multiple blocks unless it clarifies a dependency\n\n"
            f"Output JSON shape:\n{json.dumps(output_shape, ensure_ascii=False, indent=2)}\n\n"
            f"Registry manifest:\n{json.dumps(manifest, ensure_ascii=False, indent=2)}\n\n"
            f"Assistant response to transform:\n{response}"
        )
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    async def _plan_visual_digest(self, event: MessageEvent, response: str) -> Optional[dict]:
        from agent.auxiliary_client import async_call_llm, extract_content_or_reasoning

        planner_response = await async_call_llm(
            task="telegram_visual_digest",
            messages=self._build_visual_digest_planner_messages(event, response),
            temperature=0.2,
            max_tokens=2200,
            timeout=45,
        )
        planner_text = extract_content_or_reasoning(planner_response).strip()
        return parse_visual_digest_plan(planner_text, response) if planner_text else None

    def _render_md_to_html(self, md_text: str) -> str:
        try:
            import markdown as md_lib

            rendered = md_lib.markdown(
                md_text, extensions=["fenced_code", "tables", "toc", "nl2br", "sane_lists"]
            )
        except Exception:
            rendered = "<pre>" + html.escape(md_text) + "</pre>"
        return sanitize_rendered_markdown_html(rendered)

    async def _maybe_deliver_long_telegram_response_as_html(
        self, event: MessageEvent, response: str
    ) -> Optional[str]:
        if event.source.platform != Platform.TELEGRAM:
            return None
        cfg = self._telegram_long_response_html_config()
        if not self._response_requires_html_document(response, cfg):
            return None
        adapter = self.adapters.get(event.source.platform)
        try:
            reply_anchor = self._reply_anchor_for_event(event)
            metadata = self._thread_metadata_for_source(event.source, reply_anchor)
            ts, _, _ = self._long_response_html_paths(event)
            sent_docs = 0
            visual_cfg = cfg.get("visual_digest") if isinstance(cfg.get("visual_digest"), dict) else {}
            hosting_cfg = cfg.get("hosting") if isinstance(cfg.get("hosting"), dict) else {}
            visual_attempted = False
            visual_sent = False
            if visual_cfg.get("enabled") and adapter and hasattr(adapter, "send_document"):
                visual_attempted = True
                try:
                    plan = await self._plan_visual_digest(event, response)
                except Exception as exc:
                    plan = None
                    logger.warning("Telegram visual planner failed: %s", exc, exc_info=True)
                if plan:
                    visual_path = self._write_visual_digest_html_file(response, event, plan=plan, ts=ts)
                    if hosting_cfg.get("enabled"):
                        hosted_url = await self._host_long_response_html(visual_path, hosting_cfg)
                        if hosted_url:
                            link_text = str(visual_cfg.get("link_text") or "Open visual report")
                            return f"[{link_text.replace('[', '').replace(']', '')}]({hosted_url})"
                    visual_result = await adapter.send_document(
                        chat_id=event.source.chat_id,
                        file_path=visual_path,
                        caption=str(visual_cfg.get("caption") or "Visual digest attached as HTML."),
                        file_name=os.path.basename(visual_path),
                        reply_to=reply_anchor,
                        metadata=metadata,
                    )
                    if getattr(visual_result, "success", False):
                        sent_docs += 1
                        visual_sent = True
                    else:
                        logger.warning(
                            "Telegram visual digest upload failed: %s",
                            getattr(visual_result, "error", "unknown"),
                        )
            if sent_docs == 0 or visual_cfg.get("send_raw_html", True):
                html_path = self._write_long_response_html_file(response, event, ts=ts)
                if hosting_cfg.get("enabled"):
                    hosted_url = await self._host_long_response_html(html_path, hosting_cfg)
                    if hosted_url:
                        link_text = str(hosting_cfg.get("link_text") or "Open full response")
                        return f"[{link_text.replace('[', '').replace(']', '')}]({hosted_url})"
                    if not hosting_cfg.get("fallback_to_attachment", True):
                        return None
                if not adapter or not hasattr(adapter, "send_document"):
                    return None
                result = await adapter.send_document(
                    chat_id=event.source.chat_id,
                    file_path=html_path,
                    caption=str(cfg.get("caption") or "Full response attached as HTML."),
                    file_name=os.path.basename(html_path),
                    reply_to=reply_anchor,
                    metadata=metadata,
                )
                if getattr(result, "success", False):
                    sent_docs += 1
                else:
                    logger.warning(
                        "Telegram long-response HTML upload failed: %s",
                        getattr(result, "error", "unknown"),
                    )
            if sent_docs > 0:
                if visual_sent and sent_docs > 1:
                    return "Visual digest and full response are attached as HTML files."
                if visual_sent:
                    return "Visual digest is attached as an HTML file."
                return str(cfg.get("notice") or "Full response is attached as an HTML file.")
            if visual_attempted:
                logger.info("Telegram visual digest did not produce a deliverable artifact")
        except Exception as exc:
            logger.warning("Telegram long-response HTML delivery failed: %s", exc, exc_info=True)
        return None
