"""首页视图冒烟测试：未登录跳转登录页，登录后正常渲染。"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

User = get_user_model()


@pytest.mark.django_db
def test_home_redirects_anonymous_user_to_login(client: Client) -> None:
    resp = client.get(reverse("dashboard:home"))
    assert resp.status_code == 302
    assert resp.url == reverse("accounts:login") + "?next=/"


@pytest.mark.django_db
def test_home_renders_for_authenticated_user(client: Client) -> None:
    User.objects.create_user(username="tester", password="pw123456")
    assert client.login(username="tester", password="pw123456")
    resp = client.get(reverse("dashboard:home"))
    assert resp.status_code == 200
    assert "今天要处理的事会显示在这里" in resp.content.decode()
