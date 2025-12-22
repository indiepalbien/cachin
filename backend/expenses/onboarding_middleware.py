"""
Middleware to redirect users through the onboarding flow.

If a user has not completed onboarding (onboarding_step != 0),
they will be redirected to the appropriate onboarding step.
"""
from django.shortcuts import redirect
from django.urls import reverse
from .models import UserProfile


class OnboardingMiddleware:
    """Redirect users to onboarding steps if they haven't completed onboarding."""
    
    # URLs that are always allowed (authentication, static files)
    ALWAYS_ALLOWED_URLS = [
        '/accounts/login/',
        '/accounts/logout/',
        '/accounts/register/',
        '/static/',
        '/media/',
    ]
    
    # Map onboarding steps to URLs
    STEP_URLS = {
        1: '/expenses/manage/categories/',
        2: '/expenses/manage/projects/',
        3: '/expenses/manage/splitwise/',
        4: '/expenses/manage/emails/',  # Email configuration
        5: '/user/',  # Profile with finish button
    }
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Skip if user is not authenticated
        if not request.user.is_authenticated:
            return self.get_response(request)
        
        # Always allow authentication and static URLs
        for allowed_url in self.ALWAYS_ALLOWED_URLS:
            if request.path.startswith(allowed_url):
                return self.get_response(request)
        
        # Get or create user profile
        try:
            profile = request.user.profile
        except UserProfile.DoesNotExist:
            # Create profile if it doesn't exist (shouldn't happen with signals)
            profile = UserProfile.objects.create(user=request.user, onboarding_step=1)
        
        # Check if onboarding is complete
        if profile.onboarding_step == 0:
            return self.get_response(request)
        
        # Get the correct URL for current onboarding step
        onboarding_url = self.STEP_URLS.get(profile.onboarding_step, '/user/')
        
        # If already on the correct page, allow access
        if request.path == onboarding_url:
            return self.get_response(request)
        
        # Also allow sub-URLs of the onboarding pages (like /add/, /edit/, etc.)
        if onboarding_url != '/user/' and request.path.startswith(onboarding_url.rstrip('/')):
            return self.get_response(request)
        
        # Redirect to the appropriate onboarding step
        return redirect(onboarding_url)
