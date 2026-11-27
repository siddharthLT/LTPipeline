from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from .models import InternalDoc

MAX_BYTES = 5 * 1024 * 1024


@login_required
def doc_list(request):
    return render(request, 'pipeline/docs.html', {'docs': InternalDoc.objects.all(), 'nav': 'docs', 'error': request.GET.get('error', '')})


@login_required
@require_POST
def doc_create(request):
    """Add a doc from an uploaded .html file or pasted HTML."""
    title = request.POST.get('title', '').strip()
    html = request.POST.get('html', '')
    upload = request.FILES.get('file')
    if upload:
        if upload.size > MAX_BYTES:
            return redirect('/docs/?error=That+file+is+over+5+MB')
        html = upload.read().decode('utf-8', errors='replace')
        title = title or upload.name.rsplit('.', 1)[0]
    if not html.strip() or not title:
        return redirect('/docs/?error=Add+a+title+and+an+HTML+file+or+pasted+HTML')
    doc = InternalDoc.objects.create(title=title[:200], note=request.POST.get('note', '').strip()[:300], html=html)
    return redirect('pipeline:doc_view', pk=doc.pk)


@login_required
def doc_view(request, pk):
    return render(request, 'pipeline/doc_view.html', {'doc': get_object_or_404(InternalDoc, pk=pk), 'nav': 'docs'})


@login_required
@xframe_options_sameorigin
def doc_raw(request, pk):
    """The document itself. The sandbox lets its own scripts run but gives it no access to this site's cookies or pages."""
    doc = get_object_or_404(InternalDoc, pk=pk)
    resp = HttpResponse(doc.html, content_type='text/html; charset=utf-8')
    resp['Content-Security-Policy'] = 'sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox'
    return resp


@login_required
@require_POST
def doc_delete(request, pk):
    get_object_or_404(InternalDoc, pk=pk).delete()
    return redirect('pipeline:docs')
