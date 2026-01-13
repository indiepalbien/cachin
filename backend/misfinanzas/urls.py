"""
URL configuration for misfinanzas project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
import os
from django.contrib import admin
from django.urls import path, include
from expenses import views as expenses_views
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView
from django.http import HttpResponse

urlpatterns = [
    path('', expenses_views.landing, name='landing'),
    path('user/', expenses_views.profile, name='profile'),
    path('expenses/', include('expenses.urls')),
    path('accounts/register/', expenses_views.register, name='register'),
    path('accounts/', include('django.contrib.auth.urls')),
    # PWA URLs (manifest, service worker)
    path('', include(('pwa.urls', 'pwa'), namespace='pwa')),
    # Serve a minimal robots.txt to avoid 404 noise
    path('robots.txt', TemplateView.as_view(
        template_name='robots.txt', content_type='text/plain'
    ), name='robots_txt'),
    # Return 204 for missing favicon to cut noise if none provided
    path('favicon.ico', lambda request: HttpResponse(status=204)),
    # Admin under configurable path (default: 'admin')
    path(f"{settings.ADMIN_URL}/", admin.site.urls),
]

# Serve static files in development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    # Serve media files in development
    if hasattr(settings, 'MEDIA_URL') and hasattr(settings, 'MEDIA_ROOT'):
        urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
