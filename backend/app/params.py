"""Paylasilan ID sinirlari: Postgres integer kolonu int32'nin ustunu KABUL ETMEZ
(asyncpg "integer out of range" -> yakalanmamis DataError -> 500). Path/body'de int
alan HER yerde tek bir alias kullanilir ki deger DB'ye hic gitmeden 422 ile reddedilsin.
"""

from typing import Annotated

from fastapi import Path
from pydantic import Field

PG_INT_MAX = 2_147_483_647

# Route imzalarinda path parametresi icin: `story_id: IdPath`
IdPath = Annotated[int, Path(ge=1, le=PG_INT_MAX)]

# Pydantic modellerinde body alani icin: `story_id: IdField`
IdField = Annotated[int, Field(ge=1, le=PG_INT_MAX)]
