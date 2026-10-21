from django.urls import path

from . import views

app_name = 'pipeline'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('playbook/', views.playbook, name='playbook'),
    path('playbook/<int:pk>/edit/', views.edit_usage_stage, name='edit_usage_stage'),
    path('accounts/<int:pk>/', views.account_detail, name='account_detail'),
    path('accounts/<int:pk>/edit/<slug:section>/', views.edit_section, name='edit_section'),
    path('accounts/<int:pk>/task/<int:item_id>/toggle/', views.toggle_task, name='task_toggle'),
    path('accounts/<int:pk>/meeting/<int:meeting_id>/part/<slug:part>/', views.edit_meeting_part, name='meeting_part'),
    path('accounts/<int:pk>/<slug:kind>/new/', views.edit_item, name='item_new'),
    path('accounts/<int:pk>/<slug:kind>/<int:item_id>/edit/', views.edit_item, name='item_edit'),
    path('accounts/<int:pk>/<slug:kind>/<int:item_id>/delete/', views.delete_item, name='item_delete'),
]
