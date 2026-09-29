"""
Django settings for core project.
"""

from pathlib import Path

from dotenv import load_dotenv
import os

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env')


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-dev-only-change-me')

DEBUG = os.getenv('DEBUG', 'False').lower() in ('true', '1', 'yes')

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
    if host.strip()
]

# Full origins (scheme + host). Required for login forms opened through ngrok,
# because the browser sends https:// while runserver receives the request as http://.
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        'CSRF_TRUSTED_ORIGINS',
        'http://127.0.0.1:8000,http://localhost:8000',
    ).split(',')
    if origin.strip()
]

# Ngrok sets X-Forwarded-Proto: https. Trust it so the request counts as secure.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'kahawa',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'kahawa.context_processors.cart',
                'kahawa.context_processors.cafe',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Africa/Nairobi'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/orders/'

# Public site URL used in SMS track links, emails, etc.
SITE_URL = os.getenv('SITE_URL', 'http://127.0.0.1:8000').rstrip('/')

# Cafe / trust details (footer + contact)
CAFE_NAME = os.getenv('CAFE_NAME', 'Kahawa')
CAFE_ADDRESS = os.getenv('CAFE_ADDRESS', 'Kimathi Street, CBD · Nairobi')
CAFE_HOURS_WEEKDAY = os.getenv('CAFE_HOURS_WEEKDAY', 'Mon–Fri 7:00–21:00')
CAFE_HOURS_WEEKEND = os.getenv('CAFE_HOURS_WEEKEND', 'Sat–Sun 8:00–22:00')
CAFE_PHONE = os.getenv('CAFE_PHONE', '+254 700 000 000')
CAFE_PHONE_TEL = os.getenv('CAFE_PHONE_TEL', '+254700000000')
CAFE_WHATSAPP = os.getenv('CAFE_WHATSAPP', '254700000000')
CAFE_MAPS_URL = os.getenv(
    'CAFE_MAPS_URL',
    'https://maps.google.com/?q=Kimathi+Street+Nairobi',
)
CAFE_PREP_PICKUP_MIN = int(os.getenv('CAFE_PREP_PICKUP_MIN', '10'))
CAFE_PREP_DELIVERY_MIN = int(os.getenv('CAFE_PREP_DELIVERY_MIN', '25'))

# Loyalty: 1 point per KSh 10 paid; 2 points = KSh 1 off (20 pts = KSh 10)
LOYALTY_POINTS_PER_KSH = os.getenv('LOYALTY_POINTS_PER_KSH', '0.1')
LOYALTY_REDEEM_POINTS_PER_KSH = int(os.getenv('LOYALTY_REDEEM_POINTS_PER_KSH', '2'))
GIFT_CARD_AMOUNTS = [500, 1000, 2000, 5000]
PAYMENT_TIMEOUT_SECONDS = int(os.getenv('PAYMENT_TIMEOUT_SECONDS', '90'))

# ---------------------------------------------------------------------------
# SMS (Africa's Talking)
# ---------------------------------------------------------------------------
SMS_PROVIDER = os.getenv('SMS_PROVIDER', 'console').lower()
AT_USERNAME = os.getenv('AT_USERNAME', 'sandbox')
AT_API_KEY = os.getenv('AT_API_KEY', '')
AT_SENDER_ID = os.getenv('AT_SENDER_ID', '')

# ---------------------------------------------------------------------------
# KRA eTIMS (OSCU)
# ---------------------------------------------------------------------------
# Blank until device initialisation. The receipt does not print a fiscal stamp yet.
ETIMS_ENV = os.getenv('ETIMS_ENV', 'sandbox').lower()  # sandbox | production
ETIMS_TIN = os.getenv('ETIMS_TIN', '')
ETIMS_BHF_ID = os.getenv('ETIMS_BHF_ID', '00')
ETIMS_DEVICE_SERIAL = os.getenv('ETIMS_DEVICE_SERIAL', '')
ETIMS_CMC_KEY = os.getenv('ETIMS_CMC_KEY', '')
_ETIMS_URLS = {
    'sandbox': 'https://etims-api-sbx.kra.go.ke/etims-api',
    'production': 'https://etims-api.kra.go.ke/etims-api',
}
ETIMS_BASE_URL = os.getenv(
    'ETIMS_BASE_URL',
    _ETIMS_URLS.get(ETIMS_ENV, _ETIMS_URLS['sandbox']),
).rstrip('/')

# ---------------------------------------------------------------------------
# M-Pesa Daraja (STK Push)
# ---------------------------------------------------------------------------
# MPESA_MODE: 'mock' (local demo) | 'live'
MPESA_MODE = os.getenv('MPESA_MODE', 'mock').lower()
MPESA_ENV = os.getenv('MPESA_ENV', 'sandbox').lower()  # sandbox | production
MPESA_CONSUMER_KEY = os.getenv('MPESA_CONSUMER_KEY', '')
MPESA_CONSUMER_SECRET = os.getenv('MPESA_CONSUMER_SECRET', '')
MPESA_SHORTCODE = os.getenv('MPESA_SHORTCODE', '')
MPESA_PASSKEY = os.getenv('MPESA_PASSKEY', '')
# Path secret for /mpesa/callback/<secret>/ — required for live; leave empty for local mock
MPESA_CALLBACK_SECRET = os.getenv('MPESA_CALLBACK_SECRET', '')
MPESA_CALLBACK_URL = os.getenv('MPESA_CALLBACK_URL', '')
