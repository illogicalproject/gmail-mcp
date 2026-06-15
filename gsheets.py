"""Google Sheets service wrapper (read-write) for the multi-account MCP server."""

from typing import Any, Dict, List, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


class SheetsService:
    def __init__(self, credentials: Credentials, account_name: str = ""):
        self.service = build("sheets", "v4", credentials=credentials)
        self.account_name = account_name

    # ------------------------------------------------------------------ create

    def create_spreadsheet(self, title: str) -> Dict[str, Any]:
        ss = self.service.spreadsheets().create(
            body={"properties": {"title": title}},
            fields="spreadsheetId,properties.title,spreadsheetUrl",
        ).execute()
        return {
            "spreadsheetId": ss["spreadsheetId"],
            "title": ss.get("properties", {}).get("title", title),
            "url": ss.get("spreadsheetUrl", ""),
        }

    def add_sheet(self, spreadsheet_id: str, title: str) -> Dict[str, Any]:
        result = self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
        ).execute()
        props = result.get("replies", [{}])[0].get("addSheet", {}).get("properties", {})
        return {"spreadsheetId": spreadsheet_id, "addedSheet": props}

    # ------------------------------------------------------------------ read

    def get_info(self, spreadsheet_id: str) -> Dict[str, Any]:
        ss = self.service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields="spreadsheetId,properties.title,spreadsheetUrl,sheets.properties",
        ).execute()
        sheets = [
            {
                "title": s["properties"].get("title", ""),
                "sheetId": s["properties"].get("sheetId"),
                "rowCount": s["properties"].get("gridProperties", {}).get("rowCount"),
                "columnCount": s["properties"].get("gridProperties", {}).get("columnCount"),
            }
            for s in ss.get("sheets", [])
        ]
        return {
            "spreadsheetId": ss["spreadsheetId"],
            "title": ss.get("properties", {}).get("title", ""),
            "url": ss.get("spreadsheetUrl", ""),
            "sheets": sheets,
        }

    def read_range(self, spreadsheet_id: str, range_a1: str) -> Dict[str, Any]:
        result = self.service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=range_a1
        ).execute()
        values = result.get("values", [])
        return {
            "range": result.get("range", range_a1),
            "rowCount": len(values),
            "values": values,
        }

    # ------------------------------------------------------------------ write

    def write_range(
        self,
        spreadsheet_id: str,
        range_a1: str,
        values: List[List[Any]],
        value_input_option: str = "USER_ENTERED",
    ) -> Dict[str, Any]:
        result = self.service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range_a1,
            valueInputOption=value_input_option,
            body={"values": values},
        ).execute()
        return {
            "spreadsheetId": spreadsheet_id,
            "updatedRange": result.get("updatedRange", ""),
            "updatedCells": result.get("updatedCells", 0),
        }

    def append_rows(
        self,
        spreadsheet_id: str,
        range_a1: str,
        values: List[List[Any]],
        value_input_option: str = "USER_ENTERED",
    ) -> Dict[str, Any]:
        result = self.service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_a1,
            valueInputOption=value_input_option,
            insertDataOption="INSERT_ROWS",
            body={"values": values},
        ).execute()
        updates = result.get("updates", {})
        return {
            "spreadsheetId": spreadsheet_id,
            "updatedRange": updates.get("updatedRange", ""),
            "updatedRows": updates.get("updatedRows", 0),
            "updatedCells": updates.get("updatedCells", 0),
        }

    def clear_range(self, spreadsheet_id: str, range_a1: str) -> Dict[str, Any]:
        result = self.service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id, range=range_a1
        ).execute()
        return {"spreadsheetId": spreadsheet_id, "clearedRange": result.get("clearedRange", "")}
