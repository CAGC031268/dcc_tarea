# Agente de Soporte LLM — App web para Cloud Run

App web (FastAPI) de la solución del laboratorio `clase09_agentes_firebase.ipynb`:
chat con el agente, LLM planner vía OpenRouter, herramientas controladas sobre
Firestore, confirmación humana para acciones sensibles y memoria de interacciones.

## Archivos

- `main.py` — servidor FastAPI + interfaz de chat (HTML en un solo archivo).
- `agente.py` — toda la lógica del agente (planner LLM, validación, herramientas, memoria).
- `Dockerfile`, `requirements.txt`, `.dockerignore` — empaquetado para Cloud Run.

## Desplegar en Cloud Run (≈5 minutos)

> Importante: despliega en el MISMO proyecto donde está tu Firestore
> (`agente-soporte-99b3c`). Así la app usa las credenciales automáticas del
> servicio y NO necesitas subir ningún archivo JSON de credenciales.

1. En Google Cloud Console, verifica en el selector de proyecto (arriba a la
   izquierda) que estás en `agente-soporte-99b3c`. Si "Dcc Agentes" es otro
   proyecto, cámbiate.
2. Abre **Cloud Shell** (ícono `>_` arriba a la derecha).
3. Sube el archivo `agente_webapp.zip` (menú `⋮` de Cloud Shell → *Subir*).
4. Ejecuta (reemplaza `TU_KEY` por tu API key de OpenRouter):

```bash
unzip -o agente_webapp.zip -d agente_webapp && cd agente_webapp

gcloud config set project agente-soporte-99b3c

gcloud run deploy agente-soporte \
  --source . \
  --region southamerica-west1 \
  --allow-unauthenticated \
  --set-env-vars OPENROUTER_API_KEY=TU_KEY
```

La primera vez, gcloud pedirá habilitar las APIs de Cloud Run, Cloud Build y
Artifact Registry — responde `y`. El build tarda 3–5 minutos y al final imprime
la **Service URL**: esa es tu app corriendo.

`southamerica-west1` es la región de Santiago; puedes usar `us-central1` si prefieres.

## Verificar

- Abre la Service URL: deberías ver el chat con dos indicadores arriba:
  **LLM: <modelo>** y **Firestore: conectado**.
- Prueba: "Dame un resumen de tickets", "Cierra tic_002" (pedirá confirmación
  con botón), "Avísale a Carla Soto que su caso fue escalado" (confirmación).
- `GET /api/info` muestra el estado; `GET /api/memoria` las últimas trazas.

## Si Firestore aparece en "modo demo (memoria)"

La service account por defecto de Cloud Run no tiene acceso a Firestore. Dale el rol:

```bash
PROJECT=agente-soporte-99b3c
SA=$(gcloud iam service-accounts list --filter="compute@" --format="value(email)")
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$SA" --role="roles/datastore.user"
```

y vuelve a desplegar o reinicia la revisión.

## Notas de seguridad

- `--allow-unauthenticated` deja la URL pública: cualquiera con el link puede
  crear/modificar tickets demo. Para la entrega está bien; después puedes
  eliminar el servicio (`gcloud run services delete agente-soporte --region southamerica-west1`).
- La API key va como variable de entorno del servicio, nunca en el código.
  Para algo más serio, usa Secret Manager (`--set-secrets`).
- El `.dockerignore` excluye `*.json` para que ninguna credencial entre a la imagen.

## Cambiar el modelo LLM

Variable de entorno `LLM_MODELOS` (lista separada por comas, se usa el primero
que responda). Catálogo vigente: https://openrouter.ai/models
