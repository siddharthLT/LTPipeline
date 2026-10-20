from django.test import TestCase
from django.urls import reverse

from .models import User


class LoginTests(TestCase):
    def setUp(self):
        User.objects.create_user('Me@Example.com', 'pw-12345-xyz')

    def test_dashboard_requires_login(self):
        r = self.client.get(reverse('pipeline:dashboard'))
        self.assertRedirects(r, f"{reverse('accounts:login')}?next=/")

    def test_login_with_email(self):
        r = self.client.post(reverse('accounts:login'), {'username': 'me@example.com', 'password': 'pw-12345-xyz'})
        self.assertRedirects(r, reverse('pipeline:dashboard'))

    def test_bad_password(self):
        r = self.client.post(reverse('accounts:login'), {'username': 'me@example.com', 'password': 'nope'})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.wsgi_request.user.is_authenticated)

    def test_logout(self):
        self.client.login(username='me@example.com', password='pw-12345-xyz')
        self.client.post(reverse('accounts:logout'))
        self.assertRedirects(self.client.get(reverse('pipeline:dashboard')), f"{reverse('accounts:login')}?next=/")
