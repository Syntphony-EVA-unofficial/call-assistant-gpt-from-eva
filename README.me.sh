docker build -t [REGION]-docker.pkg.dev/[PROJECT_ID]/[REPOSITORY]/[IMAGE_NAME]:[TAG] .

docker push [REGION]-docker.pkg.dev/[PROJECT_ID]/[REPOSITORY]/[IMAGE_NAME]:[TAG]

gcloud run deploy [SERVICE_NAME] --image [REGION]-docker.pkg.dev/[PROJECT_ID]/[REPOSITORY]/[IMAGE_NAME]:[TAG] --platform managed --allow-unauthenticated --set-env-vars OPENAI_API_KEY="[API_KEY]"