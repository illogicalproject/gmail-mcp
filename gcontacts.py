"""Google Contacts (People API) wrapper — read + write — for the MCP server.

Write methods (create/update/delete) require the full
``https://www.googleapis.com/auth/contacts`` scope; the read-only scope will
return a 403 on those calls."""

from typing import Any, Dict, List, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

_PERSON_FIELDS = "names,emailAddresses,phoneNumbers,organizations"
_READ_MASK = "names,emailAddresses,phoneNumbers,organizations"


class ContactsService:
    def __init__(self, credentials: Credentials, account_name: str = ""):
        self.service = build("people", "v1", credentials=credentials)
        self.account_name = account_name

    def search(self, query: str, max_results: int = 15) -> Dict[str, Any]:
        """Search the user's contacts by name, email, phone, etc.

        The People API keeps a per-session search cache that must be warmed with
        an initial request, so we send a throwaway warmup call first (Google's
        documented pattern) before the real query."""
        try:
            self.service.people().searchContacts(
                query="", readMask=_READ_MASK, pageSize=1
            ).execute()
        except Exception:
            pass  # warmup is best-effort
        result = self.service.people().searchContacts(
            query=query,
            readMask=_READ_MASK,
            pageSize=min(max_results, 30),
        ).execute()
        people = [self._parse_person(r.get("person", {})) for r in result.get("results", [])]
        return {"query": query, "count": len(people), "contacts": people}

    def list_contacts(self, max_results: int = 50) -> Dict[str, Any]:
        result = self.service.people().connections().list(
            resourceName="people/me",
            pageSize=min(max_results, 200),
            personFields=_PERSON_FIELDS,
            sortOrder="LAST_MODIFIED_DESCENDING",
        ).execute()
        people = [self._parse_person(p) for p in result.get("connections", [])]
        return {
            "count": len(people),
            "contacts": people,
            "nextPageToken": result.get("nextPageToken", ""),
        }

    # ------------------------------------------------------------------ write

    def create_contact(
        self,
        name: Optional[str] = None,
        given_name: Optional[str] = None,
        family_name: Optional[str] = None,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        organization: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new contact. Provide at least one of name / given_name /
        family_name / email. ``name`` is used as an unstructured full name when
        given/family parts are not supplied."""
        body = self._build_person_body(
            name, given_name, family_name, email, phone, organization
        )
        if not body:
            raise ValueError("Provide at least a name or email to create a contact.")
        person = self.service.people().createContact(body=body).execute()
        return {
            "created": True,
            "resourceName": person.get("resourceName", ""),
            "contact": self._parse_person(person),
        }

    def update_contact(
        self,
        resource_name: str,
        name: Optional[str] = None,
        given_name: Optional[str] = None,
        family_name: Optional[str] = None,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        organization: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update an existing contact. Only the fields you pass are changed.
        Reads the contact first to obtain its current etag (required by the
        People API to guard against concurrent edits)."""
        existing = self.service.people().get(
            resourceName=resource_name, personFields=_PERSON_FIELDS
        ).execute()

        body: Dict[str, Any] = {"etag": existing.get("etag")}
        update_fields: List[str] = []

        if name or given_name or family_name:
            n: Dict[str, str] = {}
            if given_name:
                n["givenName"] = given_name
            if family_name:
                n["familyName"] = family_name
            if name and not (given_name or family_name):
                n["unstructuredName"] = name
            body["names"] = [n]
            update_fields.append("names")
        if email is not None:
            body["emailAddresses"] = [{"value": email}]
            update_fields.append("emailAddresses")
        if phone is not None:
            body["phoneNumbers"] = [{"value": phone}]
            update_fields.append("phoneNumbers")
        if organization is not None:
            body["organizations"] = [{"name": organization}]
            update_fields.append("organizations")

        if not update_fields:
            raise ValueError("No fields provided to update.")

        person = self.service.people().updateContact(
            resourceName=resource_name,
            updatePersonFields=",".join(update_fields),
            body=body,
        ).execute()
        return {
            "updated": True,
            "resourceName": person.get("resourceName", ""),
            "contact": self._parse_person(person),
        }

    def delete_contact(self, resource_name: str) -> Dict[str, Any]:
        """Permanently delete a contact by its resourceName (e.g. people/c123)."""
        self.service.people().deleteContact(resourceName=resource_name).execute()
        return {"deleted": True, "resourceName": resource_name}

    # ------------------------------------------------------------------ internals

    def _build_person_body(
        self,
        name: Optional[str],
        given_name: Optional[str],
        family_name: Optional[str],
        email: Optional[str],
        phone: Optional[str],
        organization: Optional[str],
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if name or given_name or family_name:
            n: Dict[str, str] = {}
            if given_name:
                n["givenName"] = given_name
            if family_name:
                n["familyName"] = family_name
            if name and not (given_name or family_name):
                n["unstructuredName"] = name
            body["names"] = [n]
        if email:
            body["emailAddresses"] = [{"value": email}]
        if phone:
            body["phoneNumbers"] = [{"value": phone}]
        if organization:
            body["organizations"] = [{"name": organization}]
        return body

    def _parse_person(self, p: Dict[str, Any]) -> Dict[str, Any]:
        names = p.get("names", [])
        orgs = p.get("organizations", [])
        return {
            "resourceName": p.get("resourceName", ""),
            "name": names[0].get("displayName", "") if names else "",
            "emails": [e.get("value", "") for e in p.get("emailAddresses", [])],
            "phones": [ph.get("value", "") for ph in p.get("phoneNumbers", [])],
            "organization": orgs[0].get("name", "") if orgs else "",
        }
