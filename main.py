from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
from bs4 import BeautifulSoup
import re
from typing import Optional
import os

app = FastAPI(title="Tarificateur Sectorem")

# Configuration CORS pour permettre les appels depuis le frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration des identifiants
LUXIOR_ID = os.getenv("LUXIOR_ID", "443402")
AMI3F_ID = os.getenv("AMI3F_ID", "9133")
ODOO_API_KEY = os.getenv("ODOO_API_KEY", "")

class ProduitRequest(BaseModel):
    reference: str
    fournisseur: str  # "luxior" ou "ami3f"

class ProduitResponse(BaseModel):
    reference: str
    fournisseur: str
    prix: Optional[float] = None
    designation: Optional[str] = None
    disponibilite: Optional[str] = None
    erreur: Optional[str] = None

@app.get("/")
async def root():
    return {
        "message": "Tarificateur Sectorem API",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "recherche": "/api/recherche (POST)",
            "docs": "/docs"
        }
    }

@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "luxior_configured": bool(LUXIOR_ID),
        "ami3f_configured": bool(AMI3F_ID),
        "odoo_configured": bool(ODOO_API_KEY)
    }

async def scrape_luxior(reference: str) -> ProduitResponse:
    """Scrape les données depuis Luxior"""
    try:
        url = f"https://www.luxior.fr/catalog/product/view/id/{LUXIOR_ID}"
        
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            # Première requête pour obtenir la page de recherche
            search_url = f"https://www.luxior.fr/catalogsearch/result/?q={reference}"
            response = await client.get(search_url)
            
            if response.status_code != 200:
                return ProduitResponse(
                    reference=reference,
                    fournisseur="luxior",
                    erreur=f"Erreur HTTP {response.status_code}"
                )
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Recherche du produit dans les résultats
            product_item = soup.find('div', class_='product-item-info')
            
            if not product_item:
                return ProduitResponse(
                    reference=reference,
                    fournisseur="luxior",
                    erreur="Produit non trouvé"
                )
            
            # Extraction du nom
            name_element = product_item.find('a', class_='product-item-link')
            designation = name_element.text.strip() if name_element else "N/A"
            
            # Extraction du prix
            price_element = product_item.find('span', class_='price')
            prix_text = price_element.text.strip() if price_element else None
            
            prix = None
            if prix_text:
                # Nettoyer le prix (enlever €, espaces, etc.)
                prix_clean = re.sub(r'[^\d,.]', '', prix_text).replace(',', '.')
                try:
                    prix = float(prix_clean)
                except ValueError:
                    pass
            
            # Extraction de la disponibilité
            stock_element = product_item.find('div', class_='stock')
            disponibilite = stock_element.text.strip() if stock_element else "À vérifier"
            
            return ProduitResponse(
                reference=reference,
                fournisseur="luxior",
                prix=prix,
                designation=designation,
                disponibilite=disponibilite
            )
            
    except httpx.TimeoutException:
        return ProduitResponse(
            reference=reference,
            fournisseur="luxior",
            erreur="Timeout - Le serveur Luxior ne répond pas"
        )
    except Exception as e:
        return ProduitResponse(
            reference=reference,
            fournisseur="luxior",
            erreur=f"Erreur: {str(e)}"
        )

async def scrape_ami3f(reference: str) -> ProduitResponse:
    """Scrape les données depuis AMI 3F"""
    try:
        # URL de recherche AMI 3F
        search_url = f"https://www.ami3f.com/recherche?q={reference}"
        
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(search_url)
            
            if response.status_code != 200:
                return ProduitResponse(
                    reference=reference,
                    fournisseur="ami3f",
                    erreur=f"Erreur HTTP {response.status_code}"
                )
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Recherche du produit (adapter selon la structure réelle du site)
            product_card = soup.find('div', class_='product-card')
            
            if not product_card:
                # Essayer une autre structure
                product_card = soup.find('article', class_='product')
            
            if not product_card:
                return ProduitResponse(
                    reference=reference,
                    fournisseur="ami3f",
                    erreur="Produit non trouvé"
                )
            
            # Extraction du nom
            name_element = product_card.find(['h2', 'h3', 'a'], class_=re.compile('product.*title|name'))
            designation = name_element.text.strip() if name_element else "N/A"
            
            # Extraction du prix
            price_element = product_card.find(['span', 'div'], class_=re.compile('price'))
            prix_text = price_element.text.strip() if price_element else None
            
            prix = None
            if prix_text:
                prix_clean = re.sub(r'[^\d,.]', '', prix_text).replace(',', '.')
                try:
                    prix = float(prix_clean)
                except ValueError:
                    pass
            
            # Extraction de la disponibilité
            stock_element = product_card.find(['span', 'div'], class_=re.compile('stock|availability'))
            disponibilite = stock_element.text.strip() if stock_element else "À vérifier"
            
            return ProduitResponse(
                reference=reference,
                fournisseur="ami3f",
                prix=prix,
                designation=designation,
                disponibilite=disponibilite
            )
            
    except httpx.TimeoutException:
        return ProduitResponse(
            reference=reference,
            fournisseur="ami3f",
            erreur="Timeout - Le serveur AMI 3F ne répond pas"
        )
    except Exception as e:
        return ProduitResponse(
            reference=reference,
            fournisseur="ami3f",
            erreur=f"Erreur: {str(e)}"
        )

@app.post("/api/recherche", response_model=ProduitResponse)
async def recherche_produit(produit: ProduitRequest):
    """Recherche un produit sur le fournisseur spécifié"""
    
    if not produit.reference or not produit.reference.strip():
        raise HTTPException(status_code=400, detail="La référence est obligatoire")
    
    fournisseur = produit.fournisseur.lower()
    
    if fournisseur == "luxior":
        return await scrape_luxior(produit.reference)
    elif fournisseur == "ami3f":
        return await scrape_ami3f(produit.reference)
    else:
        raise HTTPException(
            status_code=400, 
            detail="Fournisseur non supporté. Utilisez 'luxior' ou 'ami3f'"
        )

@app.get("/api/test-luxior/{reference}")
async def test_luxior(reference: str):
    """Endpoint de test pour Luxior"""
    return await scrape_luxior(reference)

@app.get("/api/test-ami3f/{reference}")
async def test_ami3f(reference: str):
    """Endpoint de test pour AMI 3F"""
    return await scrape_ami3f(reference)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
