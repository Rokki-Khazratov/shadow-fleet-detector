"""Read-only local catalogue of cited signal bindings and external claims."""
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, field_validator, model_validator

MAX_CATALOG_BYTES = 512 * 1024
Slug = Annotated[str, StringConstraints(pattern=r'^[a-z0-9][a-z0-9_-]{0,47}$')]
Mmsi = Annotated[str, StringConstraints(pattern=r'^[0-9]{9}$')]
Identifier = Annotated[str, StringConstraints(min_length=1, max_length=100)]


class Entry(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)


class Citation(Entry):
    title: str = Field(min_length=1, max_length=200)
    url: HttpUrl
    retrieved_on: date
    license_note: str = Field(min_length=1, max_length=400)

    @field_validator('url')
    @classmethod
    def secure_source_url(cls, url: HttpUrl) -> HttpUrl:
        if url.scheme != 'https' or url.username is not None or url.password is not None:
            raise ValueError('Citation URL must be HTTPS without user information')
        return url


class Subject(Entry):
    namespace: Slug
    identifier: Identifier

    def key(self) -> tuple[str, str]:
        return self.namespace, self.identifier


class Binding(Subject):
    source_id: Slug
    mmsi: Mmsi
    since: date
    until: date
    citation: Citation

    @model_validator(mode='after')
    def check_interval(self):
        if self.since >= self.until:
            raise ValueError('Binding interval must be positive')
        return self


class ExternalClaim(Subject):
    kind: Literal['registry_record', 'authority_notice', 'research_note']
    statement: str = Field(min_length=1, max_length=800)
    published_on: date
    citation: Citation


class Dossier(Entry):
    source_id: Slug
    mmsi: Mmsi
    on: date
    status: Literal['not_configured', 'no_link', 'linked', 'ambiguous']
    bindings: tuple[Binding, ...] = ()
    external_claims: tuple[ExternalClaim, ...] = ()


class Catalog(Entry):
    bindings: tuple[Binding, ...] = Field(max_length=1000)
    claims: tuple[ExternalClaim, ...] = Field(max_length=1000)

    @classmethod
    def load(cls, path: Path):
        try:
            if not path.is_file():
                raise ValueError('not a regular file')
            with path.open('rb') as stream:
                data = stream.read(MAX_CATALOG_BYTES + 1)
            if len(data) > MAX_CATALOG_BYTES:
                raise ValueError('catalog exceeds size limit')
            return cls.model_validate_json(data)
        except (OSError, ValueError):
            raise ValueError('Invalid dossier catalog') from None

    def dossier(self, source_id: str, mmsi: str, on: date) -> Dossier:
        bindings = tuple(b for b in self.bindings if b.source_id == source_id and b.mmsi == mmsi
                         and b.since <= on < b.until)
        keys = {b.key() for b in bindings}
        if len(keys) != 1:
            return Dossier(source_id=source_id, mmsi=mmsi, on=on,
                           status='ambiguous' if keys else 'no_link', bindings=bindings)
        claims = tuple(sorted((c for c in self.claims if c.key() in keys and c.published_on <= on),
                              key=lambda claim: claim.published_on, reverse=True))
        return Dossier(source_id=source_id, mmsi=mmsi, on=on, status='linked',
                       bindings=bindings, external_claims=claims)
