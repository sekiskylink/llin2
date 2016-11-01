from django.contrib.auth import authenticate

# ln -s /Users/sam/projects/rapidpro/temba temba
# export DJANGO_SETTINGS_MODULE=temba.settings

user = authenticate(username='sam', password='sam')
print user
print user.is_active
