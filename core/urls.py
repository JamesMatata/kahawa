"""
URL configuration for core project.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    # Django admin removed — cafe ops lives at /manage/
    path(
        'admin/',
        RedirectView.as_view(url='/manage/', permanent=False),
    ),
    path(
        'admin/<path:rest>',
        RedirectView.as_view(url='/manage/', permanent=False),
    ),
    path('', include('kahawa.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
