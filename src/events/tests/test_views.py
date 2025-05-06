import calendar
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from app.models import Item, MediaTypes, Sources
from events.models import Event


class CalendarViewTests(TestCase):
    """Tests for the calendar views."""

    def setUp(self):
        """Set up test data."""
        self.credentials = {"username": "testuser", "password": "testpassword"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    @patch("events.models.Event.objects.get_user_events")
    @patch.object(get_user_model(), "update_preference")
    def test_calendar_default_view(
        self,
        mock_update_preference,
        mock_get_user_events,
    ):
        """Test the calendar view with default parameters."""
        # Set up mocks
        mock_update_preference.return_value = "month"
        mock_get_user_events.return_value = []

        # Make the request
        response = self.client.get(reverse("calendar"))

        # Check response
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "events/calendar.html")

        # Check that the view called the mocked methods
        mock_update_preference.assert_called_once_with("calendar_layout", None)

        # Get today's date for verification
        today = timezone.localdate()
        first_day = date(today.year, today.month, 1)

        # Calculate last day of the month
        december = 12
        if today.month == december:
            last_day = date(today.year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = date(today.year, today.month + 1, 1) - timedelta(days=1)

        mock_get_user_events.assert_called_once_with(self.user, first_day, last_day)

        # Check context data
        self.assertEqual(response.context["month"], today.month)
        self.assertEqual(response.context["year"], today.year)
        self.assertEqual(
            response.context["month_name"],
            calendar.month_name[today.month],
        )
        self.assertEqual(response.context["view_type"], "month")
        self.assertEqual(response.context["today"], today)

    @patch("events.models.Event.objects.get_user_events")
    @patch.object(get_user_model(), "update_preference")
    def test_calendar_with_month_year_params(
        self,
        mock_update_preference,
        mock_get_user_events,
    ):
        """Test the calendar view with month and year parameters."""
        # Set up mocks
        mock_update_preference.return_value = "month"
        mock_get_user_events.return_value = []

        # Make the request with specific month and year
        response = self.client.get(reverse("calendar") + "?month=6&year=2024")

        # Check response
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "events/calendar.html")

        # Check that the view called the mocked methods
        mock_update_preference.assert_called_once_with("calendar_layout", None)

        # Verify date range for June 2024
        first_day = date(2024, 6, 1)
        last_day = date(2024, 7, 1) - timedelta(days=1)
        mock_get_user_events.assert_called_once_with(self.user, first_day, last_day)

        # Check context data
        self.assertEqual(response.context["month"], 6)
        self.assertEqual(response.context["year"], 2024)
        self.assertEqual(response.context["month_name"], "June")
        self.assertEqual(response.context["prev_month"], 5)
        self.assertEqual(response.context["prev_year"], 2024)
        self.assertEqual(response.context["next_month"], 7)
        self.assertEqual(response.context["next_year"], 2024)

    @patch("events.models.Event.objects.get_user_events")
    @patch.object(get_user_model(), "update_preference")
    def test_calendar_with_view_param(
        self,
        mock_update_preference,
        mock_get_user_events,
    ):
        """Test the calendar view with view parameter."""
        # Set up mocks
        mock_update_preference.return_value = "list"
        mock_get_user_events.return_value = []

        # Make the request with view parameter
        response = self.client.get(reverse("calendar") + "?view=list")

        # Check response
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "events/calendar.html")

        # Check that the view called the mocked methods
        mock_update_preference.assert_called_once_with("calendar_layout", "list")

        # Check context data
        self.assertEqual(response.context["view_type"], "list")

    @patch("events.models.Event.objects.get_user_events")
    @patch.object(get_user_model(), "update_preference")
    def test_calendar_with_invalid_month_year(
        self,
        mock_update_preference,
        mock_get_user_events,
    ):
        """Test the calendar view with invalid month and year parameters."""
        # Set up mocks
        mock_update_preference.return_value = "month"
        mock_get_user_events.return_value = []

        # Make the request with invalid month and year
        response = self.client.get(
            reverse("calendar") + "?month=invalid&year=invalid",
        )

        # Check response
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "events/calendar.html")

        # Get today's date for verification
        today = timezone.localdate()

        # Check context data - should default to current month/year
        self.assertEqual(response.context["month"], today.month)
        self.assertEqual(response.context["year"], today.year)

    @patch("events.models.Event.objects.get_user_events")
    @patch.object(get_user_model(), "update_preference")
    def test_calendar_december_navigation(
        self,
        mock_update_preference,
        mock_get_user_events,
    ):
        """Test the calendar navigation for December."""
        # Set up mocks
        mock_update_preference.return_value = "month"
        mock_get_user_events.return_value = []

        # Make the request for December
        response = self.client.get(reverse("calendar") + "?month=12&year=2024")

        # Check context data for navigation
        self.assertEqual(response.context["prev_month"], 11)
        self.assertEqual(response.context["prev_year"], 2024)
        self.assertEqual(response.context["next_month"], 1)
        self.assertEqual(response.context["next_year"], 2025)

    @patch("events.models.Event.objects.get_user_events")
    @patch.object(get_user_model(), "update_preference")
    def test_calendar_january_navigation(
        self,
        mock_update_preference,
        mock_get_user_events,
    ):
        """Test the calendar navigation for January."""
        # Set up mocks
        mock_update_preference.return_value = "month"
        mock_get_user_events.return_value = []

        # Make the request for January
        response = self.client.get(reverse("calendar") + "?month=1&year=2024")

        # Check context data for navigation
        self.assertEqual(response.context["prev_month"], 12)
        self.assertEqual(response.context["prev_year"], 2023)
        self.assertEqual(response.context["next_month"], 2)
        self.assertEqual(response.context["next_year"], 2024)

    @patch("events.models.Event.objects.get_user_events")
    @patch.object(get_user_model(), "update_preference")
    def test_calendar_with_events(
        self,
        mock_update_preference,
        mock_get_user_events,
    ):
        """Test the calendar with events."""
        # Set up mocks
        mock_update_preference.return_value = "month"

        item1 = Item(
            id=1,
            media_id="123",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Test Show 1",
            image="https://example.com/image1.jpg",
        )

        item2 = Item(
            id=2,
            media_id="456",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MOVIE.value,
            title="Test Movie",
            image="https://example.com/image2.jpg",
        )

        # Create some mock events
        today = timezone.localdate()
        event1 = Event(
            item=item1,
            datetime=timezone.make_aware(
                timezone.datetime(today.year, today.month, 15, 12, 0),
            ),
        )
        event2 = Event(
            item=item1,
            content_number=2,
            datetime=timezone.make_aware(
                timezone.datetime(today.year, today.month, 15, 18, 0),
            ),
        )
        event3 = Event(
            item=item2,
            datetime=timezone.make_aware(
                timezone.datetime(today.year, today.month, 20, 9, 0),
            ),
        )

        mock_get_user_events.return_value = [event1, event2, event3]

        # Make the request
        response = self.client.get(reverse("calendar"))

        # Check response
        self.assertEqual(response.status_code, 200)

        # Check release_dict in context
        release_dict = response.context["release_dict"]
        self.assertEqual(len(release_dict), 2)  # Two days with events
        self.assertEqual(len(release_dict[15]), 2)  # Two events on the 15th
        self.assertEqual(len(release_dict[20]), 1)  # One event on the 20th

    @patch("events.tasks.reload_calendar.delay")
    def test_reload_calendar(self, mock_reload_task):
        """Test the reload_calendar view."""
        # Make the request
        response = self.client.post(reverse("reload_calendar"))

        # Check response
        self.assertRedirects(response, reverse("calendar"))

        # Check that the task was called
        mock_reload_task.assert_called_once_with(self.user)

        # Check for message
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("refresh upcoming releases", str(messages[0]))

    def test_reload_calendar_get_method_not_allowed(self):
        """Test that GET requests to reload_calendar are not allowed."""
        # Make a GET request
        response = self.client.get(reverse("reload_calendar"))

        # Check response - should be 405 Method Not Allowed
        self.assertEqual(response.status_code, 405)
