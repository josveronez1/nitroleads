import json
from datetime import timedelta
from unittest.mock import patch

import jwt
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase
from django.utils import timezone

from lead_extractor.middleware import SupabaseAuthMiddleware
from lead_extractor.models import UserProfile
from lead_extractor.services.auth_service import (
    REMEMBER_ME_SESSION_AGE,
    SESSION_SUPABASE_USER_ID,
    SESSION_USER_PROFILE_ID,
    authenticate_supabase_token,
)


class AuthServiceTest(TestCase):
    def test_authenticate_supabase_token_creates_user_profile(self):
        token = jwt.encode(
            {
                'sub': 'supabase-user-1',
                'email': 'user@test.com',
                'aud': 'authenticated',
                'exp': timezone.now() + timedelta(minutes=5),
            },
            'test-secret',
            algorithm='HS256',
        )

        with patch(
            'lead_extractor.services.auth_service.get_supabase_auth_settings',
            return_value={
                'supabase_url': 'https://example.supabase.co',
                'supabase_jwt_secret': 'test-secret',
                'supabase_jwks_url': 'https://example.supabase.co/auth/v1/.well-known/jwks.json',
            },
        ):
            payload, user_profile = authenticate_supabase_token(token)

        self.assertEqual(payload['sub'], 'supabase-user-1')
        self.assertEqual(user_profile.supabase_user_id, 'supabase-user-1')
        self.assertEqual(user_profile.email, 'user@test.com')


class CreateSessionViewTest(TestCase):
    def setUp(self):
        self.user_profile = UserProfile.objects.create(
            supabase_user_id='session-user',
            email='session@test.com',
        )

    def test_create_session_sets_browser_close_expiry_by_default(self):
        with patch(
            'lead_extractor.views.authenticate_supabase_token',
            return_value=({'sub': self.user_profile.supabase_user_id}, self.user_profile),
        ):
            response = self.client.post(
                '/auth/session/',
                data=json.dumps({
                    'access_token': 'fake-token',
                    'remember_me': False,
                    'next_url': '/dashboard/',
                }),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        session = self.client.session
        self.assertEqual(session[SESSION_USER_PROFILE_ID], self.user_profile.id)
        self.assertEqual(session[SESSION_SUPABASE_USER_ID], self.user_profile.supabase_user_id)
        self.assertTrue(session.get_expire_at_browser_close())

    def test_create_session_sets_30_day_expiry_when_remember_me_enabled(self):
        with patch(
            'lead_extractor.views.authenticate_supabase_token',
            return_value=({'sub': self.user_profile.supabase_user_id}, self.user_profile),
        ):
            response = self.client.post(
                '/auth/session/',
                data=json.dumps({
                    'access_token': 'fake-token',
                    'remember_me': True,
                    'next_url': '/dashboard/',
                }),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        session = self.client.session
        self.assertFalse(session.get_expire_at_browser_close())
        self.assertGreaterEqual(session.get_expiry_age(), REMEMBER_ME_SESSION_AGE - 5)

    def test_logout_flushes_session(self):
        session = self.client.session
        session[SESSION_USER_PROFILE_ID] = self.user_profile.id
        session[SESSION_SUPABASE_USER_ID] = self.user_profile.supabase_user_id
        session.save()

        response = self.client.get('/logout/')

        self.assertEqual(response.status_code, 302)
        self.assertNotIn(SESSION_USER_PROFILE_ID, self.client.session)
        self.assertNotIn(SESSION_SUPABASE_USER_ID, self.client.session)


class SupabaseAuthMiddlewareTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = SupabaseAuthMiddleware(lambda request: None)
        self.user_profile = UserProfile.objects.create(
            supabase_user_id='middleware-user',
            email='middleware@test.com',
            onboarding_completed=True,
        )

    def _add_session(self, request):
        session_middleware = SessionMiddleware(lambda req: None)
        session_middleware.process_request(request)
        request.session.save()
        return request

    def test_middleware_loads_user_from_session(self):
        request = self._add_session(self.factory.get('/dashboard/'))
        request.session[SESSION_USER_PROFILE_ID] = self.user_profile.id
        request.session[SESSION_SUPABASE_USER_ID] = self.user_profile.supabase_user_id
        request.session.save()

        response = self.middleware.process_request(request)

        self.assertIsNone(response)
        self.assertEqual(request.user_profile, self.user_profile)
        self.assertEqual(request.supabase_user_id, self.user_profile.supabase_user_id)

    def test_middleware_redirects_when_session_is_missing(self):
        request = self._add_session(self.factory.get('/dashboard/'))

        response = self.middleware.process_request(request)

        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/?next=/dashboard/', response['Location'])

    def test_login_page_redirects_if_session_is_active(self):
        session = self.client.session
        session[SESSION_USER_PROFILE_ID] = self.user_profile.id
        session[SESSION_SUPABASE_USER_ID] = self.user_profile.supabase_user_id
        session.save()

        response = self.client.get('/login/')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/dashboard/')
