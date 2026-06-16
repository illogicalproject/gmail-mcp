"""Google Docs service wrapper (read-write) for the multi-account MCP server."""

from typing import Any, Dict, List, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

import markdown_docs


class DocsService:
    def __init__(self, credentials: Credentials, account_name: str = ""):
        self.service = build("docs", "v1", credentials=credentials)
        self.account_name = account_name

    # ------------------------------------------------------------------ create

    def create_document(self, title: str, text: Optional[str] = None) -> Dict[str, Any]:
        doc = self.service.documents().create(body={"title": title}).execute()
        doc_id = doc["documentId"]
        if text:
            self.service.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": [{"insertText": {"location": {"index": 1}, "text": text}}]},
            ).execute()
        return {
            "documentId": doc_id,
            "title": title,
            "url": f"https://docs.google.com/document/d/{doc_id}/edit",
        }

    # ------------------------------------------------- create / edit (markdown)

    def create_document_from_markdown(self, title: str, markdown: str) -> Dict[str, Any]:
        """Create a new Doc and render markdown into it as real formatting
        (headings, bold/italic, links, lists, blockquotes, tables)."""
        doc = self.service.documents().create(body={"title": title}).execute()
        doc_id = doc["documentId"]
        result = markdown_docs.render_markdown(self.service, doc_id, markdown)
        result.update({"title": title})
        return result

    def append_markdown(self, document_id: str, markdown: str) -> Dict[str, Any]:
        """Append markdown to the end of an existing Doc as real formatting."""
        return markdown_docs.render_markdown(self.service, document_id, markdown)

    def replace_with_markdown(self, document_id: str, markdown: str) -> Dict[str, Any]:
        """Clear the document body, then render markdown as real formatting."""
        markdown_docs.clear_body(self.service, document_id)
        return markdown_docs.render_markdown(self.service, document_id, markdown)

    # ------------------------------------------------------------------ read

    def read_document(self, document_id: str) -> Dict[str, Any]:
        doc = self.service.documents().get(documentId=document_id).execute()
        text = self._extract_text(doc.get("body", {}).get("content", []))
        return {
            "documentId": document_id,
            "title": doc.get("title", ""),
            "content": text,
            "url": f"https://docs.google.com/document/d/{document_id}/edit",
        }

    # ------------------------------------------------------------------ edit

    def append_text(self, document_id: str, text: str) -> Dict[str, Any]:
        doc = self.service.documents().get(documentId=document_id).execute()
        end_index = doc.get("body", {}).get("content", [])[-1].get("endIndex", 1)
        # endIndex points one past the final newline; insert just before it.
        insert_at = max(1, end_index - 1)
        self.service.documents().batchUpdate(
            documentId=document_id,
            body={"requests": [{"insertText": {"location": {"index": insert_at}, "text": text}}]},
        ).execute()
        return {"documentId": document_id, "status": "appended", "chars": len(text)}

    def replace_text(self, document_id: str, find: str, replace: str, match_case: bool = True) -> Dict[str, Any]:
        result = self.service.documents().batchUpdate(
            documentId=document_id,
            body={
                "requests": [
                    {
                        "replaceAllText": {
                            "containsText": {"text": find, "matchCase": match_case},
                            "replaceText": replace,
                        }
                    }
                ]
            },
        ).execute()
        replies = result.get("replies", [{}])
        occurrences = replies[0].get("replaceAllText", {}).get("occurrencesChanged", 0)
        return {"documentId": document_id, "status": "replaced", "occurrences": occurrences}

    # ------------------------------------------------------------------ internals

    def _extract_text(self, content: List[Dict[str, Any]]) -> str:
        out: List[str] = []
        for element in content:
            if "paragraph" in element:
                for el in element["paragraph"].get("elements", []):
                    text_run = el.get("textRun")
                    if text_run:
                        out.append(text_run.get("content", ""))
            elif "table" in element:
                for row in element["table"].get("tableRows", []):
                    for cell in row.get("tableCells", []):
                        out.append(self._extract_text(cell.get("content", [])))
        return "".join(out)
