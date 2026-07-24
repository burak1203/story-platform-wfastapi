from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Character, Item, Location, Story, User
from ..schemas import CreateElementRequest, ElementRequest
from ..security import get_current_user

router = APIRouter(prefix="/api/elements", tags=["elements"])

ELEMENT_MODELS = {
    "characters": Character,
    "locations": Location,
    "items": Item,
}


@router.post("/{kind}")
async def create_element(
    kind: str,
    request: CreateElementRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    model = ELEMENT_MODELS.get(kind)
    if model is None:
        raise HTTPException(status_code=404, detail="Geçersiz öğe türü.")

    story = await db.get(Story, request.story_id)
    if story is None or story.user_id != user.id:
        raise HTTPException(status_code=403, detail="Bu hikayeye öğe ekleme yetkiniz yok.")

    name = request.name.strip()[:120]
    if not name:
        raise HTTPException(status_code=400, detail="İsim boş olamaz.")

    existing = {e.name.casefold() for e in getattr(story, kind)}
    if name.casefold() in existing:
        raise HTTPException(status_code=409, detail=f"'{name}' zaten mevcut.")

    element = model(story_id=story.id, name=name, description=request.description.strip())
    db.add(element)
    await db.commit()
    return {"created": element.id}


async def _get_owned_element(kind: str, element_id: int, user: User, db: AsyncSession):
    model = ELEMENT_MODELS.get(kind)
    if model is None:
        raise HTTPException(status_code=404, detail="Geçersiz öğe türü.")
    element = await db.get(model, element_id)
    if element is None:
        raise HTTPException(status_code=404, detail="Öğe bulunamadı.")
    story = await db.get(Story, element.story_id)
    if story is None or story.user_id != user.id:
        raise HTTPException(status_code=403, detail="Bu öğeyi değiştirme yetkiniz yok.")
    return element


@router.put("/{kind}/{element_id}")
async def update_element(
    kind: str,
    element_id: int,
    request: ElementRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    element = await _get_owned_element(kind, element_id, user, db)
    name = request.name.strip()[:120]
    if not name:
        raise HTTPException(status_code=400, detail="İsim boş olamaz.")

    # Yeniden adlandirma baska bir kayitla cakismasin (unique kisit 500 yerine temiz 409)
    story = await db.get(Story, element.story_id)
    siblings = getattr(story, kind)
    if any(e.id != element.id and e.name.casefold() == name.casefold() for e in siblings):
        raise HTTPException(status_code=409, detail=f"'{name}' zaten mevcut.")

    element.name = name
    element.description = request.description.strip()
    await db.commit()
    return {"updated": element_id}


@router.delete("/{kind}/{element_id}")
async def delete_element(
    kind: str,
    element_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    element = await _get_owned_element(kind, element_id, user, db)
    await db.delete(element)
    await db.commit()
    return {"deleted": element_id}
