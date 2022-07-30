"""
Django settings for booksby project.

Generated by 'django-admin startproject' using Django 3.2.10.

For more information on this file, see
https://docs.djangoproject.com/en/3.2/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/3.2/ref/settings/
"""

import environ
from google.cloud import secretmanager, logging

import os
import io

# Build paths inside the project like this: BASE_DIR / 'subdir'.
# Set the project base directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# [START gaestd_py_django_secret_config]
env = environ.Env(
    # set casting, default value
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []))
env_file = os.path.join(BASE_DIR, ".env")

# Take environment variables from .env file
# environ.Env.read_env(os.path.join(BASE_DIR, '.env'))
# [START gaestd_py_django_secret_config]
if os.path.isfile(env_file):
    # Use a local secret file, if provided
    env.read_env(env_file)
elif os.environ.get("GOOGLE_CLOUD_PROJECT", None):
    # Pull secrets from Secret Manager
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")

    client = secretmanager.SecretManagerServiceClient()
    settings_name = os.environ.get("SETTINGS_NAME", "django_settings")
    name = f"projects/{project_id}/secrets/{settings_name}/versions/latest"
    payload = client.access_secret_version(
        name=name).payload.data.decode("UTF-8")

    env.read_env(io.StringIO(payload))
else:
    raise Exception(
        "No local .env or GOOGLE_CLOUD_PROJECT detected. No secrets found.")
# [END gaestd_py_django_secret_config]

# False if not in os.environ because of casting above
DEBUG = env('DEBUG')

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/3.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
# SECRET_KEY = os.environ['SECRET_KEY']
SECRET_KEY = env('SECRET_KEY')

ALLOWED_HOSTS = env('ALLOWED_HOSTS')

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin', 'django.contrib.auth',
    'django.contrib.contenttypes', 'django.contrib.sessions',
    'django.contrib.messages', 'django.contrib.staticfiles', 'books', 'user'
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'books.middleware.WwwRedirectMiddleware',
]

ROOT_URLCONF = 'booksby.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'books.context_processors.algolia',
            ],
        },
    },
]

WSGI_APPLICATION = 'booksby.wsgi.application'

# Database
# https://docs.djangoproject.com/en/3.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': env("DATABASE_NAME"),
        'USER': env("DATABASE_USER"),
        'PASSWORD': env("DATABASE_PASSWORD"),
        'HOST': env("DATABASE_HOST"),
        'PORT': env("DATABASE_PORT")
    }
}

# Password validation
# https://docs.djangoproject.com/en/3.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME':
        'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME':
        'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME':
        'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME':
        'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
# https://docs.djangoproject.com/en/3.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_L10N = True

USE_TZ = True

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/3.2/howto/static-files/

if env('ENV') == 'local':
    STATIC_URL = '/static/'
    STATIC_ROOT = os.path.join(BASE_DIR, 'static')
    STATICFILES_DIRS = [os.path.join(BASE_DIR, 'books/static')]
    MEDIA_URL = '/media/'
    MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Adding support of Google Cloud Storages
else:
    DEFAULT_FILE_STORAGE = 'booksby.gcloud.GoogleCloudMediaFileStorage'
    GS_PROJECT_ID = env('GOOGLE_CLOUD_PROJECT')
    GS_BUCKET_NAME = env('GS_BUCKET_NAME')
    MEDIA_ROOT = 'media/'
    # UPLOAD_ROOT = 'media/uploads/'
    MEDIA_URL = 'https://storage.googleapis.com/{}/'.format(GS_BUCKET_NAME)
    STATIC_URL = '/static/'
    STATIC_ROOT = os.path.join(BASE_DIR, 'static')
    STATICFILES_DIRS = [os.path.join(BASE_DIR, 'books/static')]

    # StackDriver setup
    client = logging.Client()
    # Connects the logger to the root logging handler; by default
    # this captures all logs at INFO level and higher
    client.setup_logging()

    LOGGING = {
        'version': 1,
        'handlers': {
            'stackdriver': {
                'level': 'INFO',
                'class': 'google.cloud.logging.handlers.CloudLoggingHandler',
                'client': client
            }
        },
        'loggers': {
            'django': {
                'handlers': ['stackdriver'],
                'level': 'INFO'
            }
        },
    }

    #implementation of logging to file, disabling until figuring out hot to save it in root,
    #the above implementation should log into the Cloud Logging API
    # LOGGING = {
    #     'version': 1,
    #     'disable_existing_loggers': False,
    #     'handlers': {
    #         'file': {
    #             'level':'ERROR',
    #             'class':'logging.handlers.RotatingFileHandler',
    #             'filename': 'debug.log',
    #             'maxBytes': 1024*1024*15, # 15MB
    #             'backupCount': 10,
    #             },
    #     },
    #     'loggers': {
    #         'django': {
    #             'handlers': ['file'],
    #             'level': 'ERROR',
    #             'propagate': True,
    #         },
    #     },
    # }

# Default primary key field type
# https://docs.djangoproject.com/en/3.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Custom User model that supports e-mail instead of username
AUTH_USER_MODEL = 'user.User'

# Variables needed for Algolia search to work
# https://www.algolia.com/
ALGOLIA_INDEX = env('ALGOLIA_INDEX', default='dev')
ALGOLIA_APPLICATION_ID = env('ALGOLIA_APPLICATION_ID', default='')
ALGOLIA_SEARCH_KEY = env('ALGOLIA_SEARCH_KEY', default='')
ALGOLIA_MODIFY_KEY = env('ALGOLIA_MODIFY_KEY', default='')

# for debugging sql
if env('ENV') == 'local':
    LOGGING = {
        'version': 1,
        'disable_existing_loggers': False,
        'handlers': {
            'console': {
                'level': 'DEBUG',
                'class': 'logging.StreamHandler',
            }
        },
        'loggers': {
            'django.db.backends': {
                'handlers': ['console'],
                'level': 'DEBUG',
            },
        }
    }