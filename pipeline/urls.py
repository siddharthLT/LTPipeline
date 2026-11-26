from django.conf import settings
from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = 'pipeline'

# Product usage and the pipeline tracker share this codebase; APP_MODE decides which of them a deployment serves.
usage_urls = [
    path('usage/', views.usage, name='usage'),
    path('usage/user/', views.usage_user, name='usage_user'),
    path('usage/live.json', views.usage_live, name='usage_live'),
    path('usage/insights/', views.usage_insights, name='usage_insights'),
]

from . import outreach_views as ov

pipeline_urls = [
    path('outreach/', ov.outreach_list, name='outreach'),
    path('outreach/new/', ov.outreach_create, name='outreach_create'),
    path('outreach/<int:pk>/', ov.outreach_detail, name='outreach_detail'),
    path('outreach/<int:pk>/edit/', ov.outreach_edit, name='outreach_edit'),
    path('outreach/<int:pk>/delete/', ov.outreach_delete, name='outreach_delete'),
    path('outreach/<int:pk>/step/', ov.step_save, name='outreach_step'),
    path('outreach/<int:pk>/step/<int:step_id>/delete/', ov.step_delete, name='outreach_step_delete'),
    path('outreach/<int:pk>/step/<int:step_id>/move/', ov.step_move, name='outreach_step_move'),
    path('outreach/<int:pk>/people/', ov.people_add, name='outreach_people'),
    path('outreach/<int:pk>/person/<int:person_id>/', ov.person_save, name='outreach_person'),
    path('outreach/<int:pk>/person/<int:person_id>/delete/', ov.person_delete, name='outreach_person_delete'),
    path('outreach/<int:pk>/toggle/', ov.outreach_toggle, name='outreach_toggle'),
    path('', views.dashboard, name='dashboard'),
    path('search.json', views.search_index, name='search'),
    path('hand-raisers/', views.hand_raisers, name='hand_raisers'),
    path('actions/', views.actions, name='actions'),
    path('rules/', views.rules, name='rules'),
    path('mapped-universe/', views.mapped_universe, name='mapped_universe'),
    path('mapped-universe/suggest/', views.mapped_suggest, name='mapped_suggest'),
    path('mapped-universe/<int:pk>/', views.mapped_company, name='mapped_company'),
    path('health-check/', views.health_check, name='health_check'),
    path('playbook/', views.playbook, name='playbook'),
    path('playbook/<int:pk>/edit/', views.edit_usage_stage, name='edit_usage_stage'),
    path('accounts/<int:pk>/', views.account_detail, name='account_detail'),
    path('accounts/<int:pk>/download.json', views.download_json, name='download_json'),
    path('accounts/<int:pk>/download.pdf', views.download_pdf, name='download_pdf'),
    path('accounts/<int:pk>/edit/<slug:section>/', views.edit_section, name='edit_section'),
    path('accounts/<int:pk>/stage/<int:num>/edit/', views.edit_stage, name='stage_edit'),
    path('accounts/<int:pk>/flag/<slug:flag>/toggle/', views.toggle_flag, name='flag_toggle'),
    path('accounts/<int:pk>/meeting/<int:meeting_id>/part/<slug:part>/', views.edit_meeting_part, name='meeting_part'),
    path('accounts/<int:pk>/action/<int:item_id>/toggle/', views.toggle_action, name='action_toggle'),
    path('accounts/<int:pk>/<slug:kind>/new/', views.edit_item, name='item_new'),
    path('accounts/<int:pk>/<slug:kind>/<int:item_id>/edit/', views.edit_item, name='item_edit'),
    path('accounts/<int:pk>/<slug:kind>/<int:item_id>/delete/', views.delete_item, name='item_delete'),
]

if settings.APP_MODE == 'usage':
    # the home page of the usage deployment is its Overview; 'dashboard' stays a valid name so shared links keep working
    urlpatterns = [path('', RedirectView.as_view(pattern_name='pipeline:usage'), name='dashboard')] + usage_urls
elif settings.APP_MODE == 'pipeline':
    urlpatterns = pipeline_urls
else:
    urlpatterns = pipeline_urls + usage_urls
