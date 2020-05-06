This project is a part of [whiteblue3/apoweroftrance-radio-system](https://github.com/whiteblue3/apoweroftrance-radio-system) project

# secret.json
You must define secret.json for security

- SECRET_KEY: DJango secret key
- JWT_SECRET_KEY: secret key for JWT auth. if you designed for microservice. each service must have same key
- AES_KEY: 32 bit AES256 key
- AES_SECRET: 16 bit AES256 key
- EMAIL_HOST_USER: use for sending email
- EMAIL_HOST_PASSWORD: send email account's password
- GCP_PROJECT_ID: google cloud project id
- GCP_STORAGE_BUCKET_NAME: bucket name of google cloud storage for media
- GS_BUCKET_NAME: bucket name of google cloud storage for static

