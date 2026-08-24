from types import SimpleNamespace

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import TEMPLATES_DIR
from app.core.contexto import ContextoSessao, exigir_perfil
from app.core.database import get_db
from app.services.categoria_service import CategoriaService
from app.services.subcategoria_service import SubcategoriaService

router = APIRouter(prefix="/configuracoes/categorias", tags=["Cadastros"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Gestão de categorias/subcategorias é administrativa (afeta a
# classificação de dados de todo o gabinete) — só ADMIN, conforme a
# autorização mínima definida na Fase 1.
_exigir_admin = exigir_perfil("ADMIN")


def flash_message(
    destino: str, message: str | None = None, category: str = "warning"
) -> RedirectResponse:
    redirect = RedirectResponse(destino, status_code=303)
    if message is not None:
        redirect.set_cookie(
            "flash_message", message, max_age=10, httponly=True, path="/configuracoes", samesite="lax"
        )
        redirect.set_cookie(
            "flash_category", category, max_age=10, httponly=True, path="/configuracoes", samesite="lax"
        )
    return redirect


@router.get("", response_class=HTMLResponse)
def listar(
    request: Request, db: Session = Depends(get_db), contexto: ContextoSessao = Depends(_exigir_admin)
):
    categorias = CategoriaService.listar(db, contexto.gabinete_id)
    resposta = templates.TemplateResponse(
        request=request,
        name="configuracoes/categorias_lista.html",
        context={
            "titulo": "Categorias",
            "categorias": categorias,
            "flash_message": request.cookies.get("flash_message"),
            "flash_category": request.cookies.get("flash_category", "warning"),
        },
    )
    resposta.delete_cookie("flash_message", path="/configuracoes")
    resposta.delete_cookie("flash_category", path="/configuracoes")
    return resposta


@router.get("/novo", response_class=HTMLResponse)
def novo(request: Request, contexto: ContextoSessao = Depends(_exigir_admin)):
    return templates.TemplateResponse(
        request=request,
        name="configuracoes/categoria_formulario.html",
        context={"titulo": "Nova categoria", "categoria": None},
    )


@router.post("/novo")
def criar(
    request: Request,
    nome: str = Form(...),
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(_exigir_admin),
):
    try:
        categoria = CategoriaService.criar(db, contexto.gabinete_id, nome)
    except ValueError as error:
        categoria_preenchida = SimpleNamespace(id=None, nome=nome)
        return templates.TemplateResponse(
            request=request,
            name="configuracoes/categoria_formulario.html",
            context={
                "titulo": "Nova categoria",
                "categoria": categoria_preenchida,
                "erro": str(error),
            },
            status_code=400,
        )
    return flash_message(
        f"/configuracoes/categorias/{categoria.id}",
        "Categoria cadastrada. Cadastre as subcategorias abaixo.",
        "success",
    )


@router.get("/{categoria_id}", response_class=HTMLResponse)
def visualizar(
    request: Request,
    categoria_id: int,
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(_exigir_admin),
):
    categoria = CategoriaService.obter_por_id(db, contexto.gabinete_id, categoria_id)
    if categoria is None:
        return flash_message("/configuracoes/categorias", "Categoria não encontrada.")
    subcategorias = SubcategoriaService.listar_por_categoria(db, contexto.gabinete_id, categoria_id)
    resposta = templates.TemplateResponse(
        request=request,
        name="configuracoes/categoria_detalhe.html",
        context={
            "titulo": categoria.nome,
            "categoria": categoria,
            "subcategorias": subcategorias,
            "flash_message": request.cookies.get("flash_message"),
            "flash_category": request.cookies.get("flash_category", "warning"),
        },
    )
    resposta.delete_cookie("flash_message", path="/configuracoes")
    resposta.delete_cookie("flash_category", path="/configuracoes")
    return resposta


@router.get("/{categoria_id}/editar", response_class=HTMLResponse)
def editar(
    request: Request,
    categoria_id: int,
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(_exigir_admin),
):
    categoria = CategoriaService.obter_por_id(db, contexto.gabinete_id, categoria_id)
    if categoria is None:
        return flash_message("/configuracoes/categorias", "Categoria não encontrada.")
    return templates.TemplateResponse(
        request=request,
        name="configuracoes/categoria_formulario.html",
        context={"titulo": "Editar categoria", "categoria": categoria},
    )


@router.post("/{categoria_id}/editar")
def atualizar(
    request: Request,
    categoria_id: int,
    nome: str = Form(...),
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(_exigir_admin),
):
    categoria = CategoriaService.obter_por_id(db, contexto.gabinete_id, categoria_id)
    if categoria is None:
        return flash_message("/configuracoes/categorias", "Categoria não encontrada.")
    try:
        CategoriaService.atualizar(db, categoria, nome)
    except ValueError as error:
        categoria_preenchida = SimpleNamespace(id=categoria_id, nome=nome)
        return templates.TemplateResponse(
            request=request,
            name="configuracoes/categoria_formulario.html",
            context={
                "titulo": "Editar categoria",
                "categoria": categoria_preenchida,
                "erro": str(error),
            },
            status_code=400,
        )
    return flash_message("/configuracoes/categorias", "Categoria atualizada.", "success")


@router.post("/{categoria_id}/alternar")
def alternar(
    categoria_id: int,
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(_exigir_admin),
):
    categoria = CategoriaService.obter_por_id(db, contexto.gabinete_id, categoria_id)
    if categoria is None:
        return flash_message("/configuracoes/categorias", "Categoria não encontrada.")
    CategoriaService.alternar_ativo(db, categoria)
    mensagem = "Categoria ativada." if categoria.ativo else "Categoria desativada."
    return flash_message("/configuracoes/categorias", mensagem, "success")


@router.get("/{categoria_id}/subcategorias/novo", response_class=HTMLResponse)
def nova_subcategoria(
    request: Request,
    categoria_id: int,
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(_exigir_admin),
):
    categoria = CategoriaService.obter_por_id(db, contexto.gabinete_id, categoria_id)
    if categoria is None:
        return flash_message("/configuracoes/categorias", "Categoria não encontrada.")
    return templates.TemplateResponse(
        request=request,
        name="configuracoes/subcategoria_formulario.html",
        context={"titulo": "Nova subcategoria", "categoria": categoria, "subcategoria": None},
    )


@router.post("/{categoria_id}/subcategorias/novo")
def criar_subcategoria(
    request: Request,
    categoria_id: int,
    nome: str = Form(...),
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(_exigir_admin),
):
    categoria = CategoriaService.obter_por_id(db, contexto.gabinete_id, categoria_id)
    if categoria is None:
        return flash_message("/configuracoes/categorias", "Categoria não encontrada.")
    try:
        SubcategoriaService.criar(db, contexto.gabinete_id, categoria_id, nome)
    except ValueError as error:
        subcategoria_preenchida = SimpleNamespace(id=None, nome=nome)
        return templates.TemplateResponse(
            request=request,
            name="configuracoes/subcategoria_formulario.html",
            context={
                "titulo": "Nova subcategoria",
                "categoria": categoria,
                "subcategoria": subcategoria_preenchida,
                "erro": str(error),
            },
            status_code=400,
        )
    return flash_message(
        f"/configuracoes/categorias/{categoria_id}", "Subcategoria cadastrada.", "success"
    )


@router.get("/{categoria_id}/subcategorias/{subcategoria_id}/editar", response_class=HTMLResponse)
def editar_subcategoria(
    request: Request,
    categoria_id: int,
    subcategoria_id: int,
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(_exigir_admin),
):
    categoria = CategoriaService.obter_por_id(db, contexto.gabinete_id, categoria_id)
    if categoria is None:
        return flash_message("/configuracoes/categorias", "Categoria não encontrada.")
    subcategoria = SubcategoriaService.obter_por_id(db, contexto.gabinete_id, subcategoria_id)
    if subcategoria is None or subcategoria.categoria_id != categoria_id:
        return flash_message(
            f"/configuracoes/categorias/{categoria_id}", "Subcategoria não encontrada."
        )
    return templates.TemplateResponse(
        request=request,
        name="configuracoes/subcategoria_formulario.html",
        context={"titulo": "Editar subcategoria", "categoria": categoria, "subcategoria": subcategoria},
    )


@router.post("/{categoria_id}/subcategorias/{subcategoria_id}/editar")
def atualizar_subcategoria(
    request: Request,
    categoria_id: int,
    subcategoria_id: int,
    nome: str = Form(...),
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(_exigir_admin),
):
    categoria = CategoriaService.obter_por_id(db, contexto.gabinete_id, categoria_id)
    if categoria is None:
        return flash_message("/configuracoes/categorias", "Categoria não encontrada.")
    subcategoria = SubcategoriaService.obter_por_id(db, contexto.gabinete_id, subcategoria_id)
    if subcategoria is None or subcategoria.categoria_id != categoria_id:
        return flash_message(
            f"/configuracoes/categorias/{categoria_id}", "Subcategoria não encontrada."
        )
    try:
        SubcategoriaService.atualizar(db, subcategoria, nome)
    except ValueError as error:
        subcategoria_preenchida = SimpleNamespace(id=subcategoria_id, nome=nome)
        return templates.TemplateResponse(
            request=request,
            name="configuracoes/subcategoria_formulario.html",
            context={
                "titulo": "Editar subcategoria",
                "categoria": categoria,
                "subcategoria": subcategoria_preenchida,
                "erro": str(error),
            },
            status_code=400,
        )
    return flash_message(
        f"/configuracoes/categorias/{categoria_id}", "Subcategoria atualizada.", "success"
    )


@router.post("/{categoria_id}/subcategorias/{subcategoria_id}/alternar")
def alternar_subcategoria(
    categoria_id: int,
    subcategoria_id: int,
    db: Session = Depends(get_db),
    contexto: ContextoSessao = Depends(_exigir_admin),
):
    subcategoria = SubcategoriaService.obter_por_id(db, contexto.gabinete_id, subcategoria_id)
    if subcategoria is None or subcategoria.categoria_id != categoria_id:
        return flash_message(
            f"/configuracoes/categorias/{categoria_id}", "Subcategoria não encontrada."
        )
    SubcategoriaService.alternar_ativo(db, subcategoria)
    mensagem = "Subcategoria ativada." if subcategoria.ativo else "Subcategoria desativada."
    return flash_message(f"/configuracoes/categorias/{categoria_id}", mensagem, "success")
