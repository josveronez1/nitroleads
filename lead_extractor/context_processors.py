from django.conf import settings


def meta_pixel(request):
    """Expose Meta Pixel ID to templates for the base snippet."""
    return {'META_PIXEL_ID': getattr(settings, 'META_PIXEL_ID', '') or ''}
