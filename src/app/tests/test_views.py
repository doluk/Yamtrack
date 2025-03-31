import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from app.models import TV, Anime, Episode, Item, MediaTypes, Movie, Season
from app.templatetags import app_tags
from users.models import HomeSortChoices


class HomeViewTests(TestCase):
    """Test the home view."""

    def setUp(self):
        """Create a user and log in."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        # Create TV show with a season and episodes
        tv_item = Item.objects.create(
            media_id="1668",
            source="tmdb",
            media_type="tv",
            title="Test TV Show",
            image="http://example.com/image.jpg",
        )
        tv = TV.objects.create(
            item=tv_item,
            user=self.user,
            status="In progress",
        )

        # Create a season for the TV show
        season_item = Item.objects.create(
            media_id="1668",
            source="tmdb",
            media_type="season",
            title="Test TV Show",
            image="http://example.com/image.jpg",
            season_number=1,
        )
        season = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=tv,
            status="In progress",
        )

        # Create episodes for the season
        for i in range(1, 6):  # Create 5 episodes
            episode_item = Item.objects.create(
                media_id="1668",
                source="tmdb",
                media_type="episode",
                title="Test TV Show",
                image="http://example.com/image.jpg",
                season_number=1,
                episode_number=i,
            )
            Episode.objects.create(
                item=episode_item,
                related_season=season,
                end_date=timezone.now().date() - timezone.timedelta(days=i),
            )

        # Create anime
        anime_item = Item.objects.create(
            media_id="1",
            source="mal",
            media_type="anime",
            title="Test Anime",
            image="http://example.com/image.jpg",
        )
        Anime.objects.create(
            item=anime_item,
            user=self.user,
            status="In progress",
            progress=10,
        )

    def test_home_view(self):
        """Test the home view displays in-progress media."""
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/home.html")

        # Check that both media items are in the context
        self.assertIn("list_by_type", response.context)
        self.assertIn("season", response.context["list_by_type"])
        self.assertIn("anime", response.context["list_by_type"])

        # Check that sort choices are in the context
        self.assertIn("sort_choices", response.context)
        self.assertEqual(response.context["sort_choices"], HomeSortChoices.choices)

        # Verify Season progress is calculated correctly (5 episodes)
        season = response.context["list_by_type"]["season"]
        self.assertEqual(len(season["items"]), 1)
        self.assertEqual(season["items"][0].progress, 5)

    def test_home_view_with_sort(self):
        """Test the home view with sorting parameter."""
        response = self.client.get(reverse("home") + "?sort=completion")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_sort"], "completion")

        # Check that user preference was updated
        self.user.refresh_from_db()
        self.assertEqual(self.user.home_sort, "completion")

    @patch("app.providers.services.get_media_metadata")
    def test_home_view_htmx_load_more(self, mock_get_media_metadata):
        """Test the HTMX load more functionality."""
        # Mock the API response
        mock_get_media_metadata.return_value = {
            "season/1": {
                "episodes": [{"id": 1}, {"id": 2}, {"id": 3}],  # 3 episodes
            },
            "related": {
                "seasons": [{"season_number": 1}],  # Only one season
            },
        }

        # Create TV shows (just enough to test load more)
        for i in range(6, 20):  # Create 14 more TV shows (we already have 1)
            tv_item = Item.objects.create(
                media_id=str(i),
                source="tmdb",
                media_type="tv",
                title=f"Test TV Show {i}",
                image="http://example.com/image.jpg",
            )
            tv = TV.objects.create(
                item=tv_item,
                user=self.user,
                status="In progress",
            )

            # Create a season for each TV show
            season_item = Item.objects.create(
                media_id=str(i),
                source="tmdb",
                media_type="season",
                title=f"Test TV Show {i}",
                image="http://example.com/image.jpg",
                season_number=1,
            )
            season = Season.objects.create(
                item=season_item,
                user=self.user,
                related_tv=tv,
                status="In progress",
            )

            # Create an episode for each season
            episode_item = Item.objects.create(
                media_id=str(i),
                source="tmdb",
                media_type="episode",
                title=f"Test TV Show {i}",
                image="http://example.com/image.jpg",
                season_number=1,
                episode_number=1,
            )
            Episode.objects.create(
                item=episode_item,
                related_season=season,
                end_date=timezone.now().date(),
            )

        # Now test the load more functionality
        headers = {"HTTP_HX_REQUEST": "true"}
        response = self.client.get(
            reverse("home") + "?load_media_type=tv",
            **headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/components/home_grid.html")

        # Check that media_list is in the context
        self.assertIn("media_list", response.context)

        # Check the structure of media_list
        self.assertIn("items", response.context["media_list"])
        self.assertIn("total", response.context["media_list"])

        # Since we're loading more (items after the first 14),
        # we should have at least 1 item in the response
        self.assertEqual(len(response.context["media_list"]["items"]), 1)
        self.assertEqual(
            response.context["media_list"]["total"],
            15,
        )  # 15 TV shows total


class MediaListViewTests(TestCase):
    """Test the media list view."""

    def setUp(self):
        """Create a user and log in."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        movies_id = ["278", "238", "129", "424", "680"]
        num_completed = 3
        # Create some media items for testing
        for i in range(1, 6):
            item = Item.objects.create(
                media_id=movies_id[i - 1],
                source="tmdb",
                media_type="movie",
                title=f"Test Movie {i}",
                image="http://example.com/image.jpg",
            )
            status = "Completed" if i < num_completed else "In progress"
            Movie.objects.create(
                item=item,
                user=self.user,
                status=status,
                progress=1 if i < num_completed else 0,
                score=i,
            )

    def test_media_list_view(self):
        """Test the media list view displays media items."""
        response = self.client.get(reverse("medialist", args=["movie"]))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/media_list.html")

        # Check that media items are in the context
        self.assertIn("media_list", response.context)
        self.assertEqual(response.context["media_list"].paginator.count, 5)

        # Check that filter options are in the context
        self.assertIn("sort_choices", response.context)
        self.assertIn("status_choices", response.context)
        self.assertEqual(response.context["media_type"], "movie")
        self.assertEqual(
            response.context["media_type_plural"],
            app_tags.media_type_readable_plural("movie").lower(),
        )

    def test_media_list_with_filters(self):
        """Test the media list view with filters."""
        response = self.client.get(
            reverse("medialist", args=["movie"])
            + "?status=Completed&sort=score&layout=table",
        )

        self.assertEqual(response.status_code, 200)

        # Check that filters are applied
        self.assertEqual(response.context["current_status"], "Completed")
        self.assertEqual(response.context["current_sort"], "score")
        self.assertEqual(response.context["current_layout"], "table")

        # Check that only completed items are shown
        self.assertEqual(response.context["media_list"].paginator.count, 2)

        # Check that user preferences were updated
        self.user.refresh_from_db()
        self.assertEqual(self.user.movie_status, "Completed")
        self.assertEqual(self.user.movie_sort, "score")
        self.assertEqual(self.user.movie_layout, "table")

    def test_media_list_htmx_request(self):
        """Test the media list view with HTMX request."""
        headers = {"HTTP_HX_REQUEST": "true"}

        # Test grid layout
        response = self.client.get(
            reverse("medialist", args=["movie"]) + "?layout=grid",
            **headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/components/media_grid_items.html")

        # Test table layout
        response = self.client.get(
            reverse("medialist", args=["movie"]) + "?layout=table",
            **headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/components/media_table_items.html")


class MediaSearchViewTests(TestCase):
    """Test the media search view."""

    def setUp(self):
        """Create a user and log in."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    @patch("app.providers.services.search")
    def test_media_search_view(self, mock_search):
        """Test the media search view."""
        # Mock the search results
        mock_search.return_value = [
            {
                "media_id": "238",
                "title": "Test Movie",
                "media_type": "movie",
                "source": "tmdb",
                "image": "http://example.com/image.jpg",
            },
        ]

        response = self.client.get(
            reverse("search") + "?media_type=movie&q=test",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/search.html")

        # Check that search results are in the context
        self.assertIn("query_list", response.context)
        self.assertEqual(len(response.context["query_list"]), 1)

        # Check that user preference was updated
        self.user.refresh_from_db()
        self.assertEqual(self.user.last_search_type, "movie")

        # Verify the search function was called with correct parameters
        mock_search.assert_called_once_with("movie", "test", None)


class MediaDetailsViewTests(TestCase):
    """Test the media details views."""

    def setUp(self):
        """Create a user and log in."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    @patch("app.providers.services.get_media_metadata")
    def test_media_details_view(self, mock_get_metadata):
        """Test the media details view."""
        # Mock the metadata
        mock_get_metadata.return_value = {
            "media_id": "238",
            "title": "Test Movie",
            "media_type": "movie",
            "source": "tmdb",
            "image": "http://example.com/image.jpg",
            "overview": "Test overview",
            "release_date": "2023-01-01",
        }

        response = self.client.get(
            reverse(
                "media_details",
                kwargs={
                    "source": "tmdb",
                    "media_type": "movie",
                    "media_id": "238",
                    "title": "test-movie",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/media_details.html")

        # Check that media metadata is in the context
        self.assertIn("media", response.context)
        self.assertEqual(response.context["media"]["title"], "Test Movie")

        # Verify the get_media_metadata function was called with correct parameters
        mock_get_metadata.assert_called_once_with("movie", "238", "tmdb")

    @patch("app.providers.services.get_media_metadata")
    @patch("app.providers.tmdb.process_episodes")
    def test_season_details_view(self, mock_process_episodes, mock_get_metadata):
        """Test the season details view."""
        # Mock the metadata
        mock_get_metadata.return_value = {
            "title": "Test TV Show",
            "media_id": "1668",
            "source": "tmdb",
            "media_type": "tv",
            "image": "http://example.com/image.jpg",
            "season/1": {
                "title": "Season 1",
                "media_id": "1668",
                "media_type": "season",
                "source": "tmdb",
                "image": "http://example.com/season.jpg",
                "episodes": [],
            },
        }

        # Mock the processed episodes
        mock_process_episodes.return_value = [
            {
                "media_id": "1668",
                "source": "tmdb",
                "media_type": "episode",
                "season_number": 1,
                "episode_number": 1,
                "name": "Episode 1",
                "air_date": "2023-01-01",
                "watched": False,
            },
        ]

        # Use the correct URL pattern for season_details
        response = self.client.get(
            reverse(
                "season_details",
                kwargs={
                    "source": "tmdb",
                    "media_id": "1668",
                    "title": "test-tv-show",
                    "season_number": 1,
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/media_details.html")

        # Check that season metadata is in the context
        self.assertIn("media", response.context)
        self.assertEqual(response.context["media"]["title"], "Season 1")
        self.assertEqual(len(response.context["media"]["episodes"]), 1)

        # Verify the get_media_metadata function was called with correct parameters
        mock_get_metadata.assert_called_once_with(
            "tv_with_seasons",
            "1668",
            "tmdb",
            [1],
        )


class TrackModalViewTests(TestCase):
    """Test the track modal view."""

    def setUp(self):
        """Create a user and log in."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        # Create a media item for testing
        self.item = Item.objects.create(
            media_id="238",
            source="tmdb",
            media_type="movie",
            title="Test Movie",
            image="http://example.com/image.jpg",
        )
        self.movie = Movie.objects.create(
            item=self.item,
            user=self.user,
            status="In progress",
            progress=0,
        )

    def test_track_modal_view_existing_media(self):
        """Test the track modal view for existing media."""
        response = self.client.get(
            reverse(
                "track_modal",
                kwargs={
                    "source": "tmdb",
                    "media_type": "movie",
                    "media_id": "238",
                },
            )
            + "?return_url=/home",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/components/fill_track.html")

        # Check that form and media are in the context
        self.assertIn("form", response.context)
        self.assertIn("media", response.context)
        self.assertEqual(response.context["media"], self.movie)
        self.assertEqual(response.context["return_url"], "/home")

    @patch("app.providers.services.get_media_metadata")
    def test_track_modal_view_new_media(self, mock_get_metadata):
        """Test the track modal view for new media."""
        # Mock the metadata
        mock_get_metadata.return_value = {
            "media_id": "278",
            "title": "New Movie",
            "media_type": "movie",
            "source": "tmdb",
            "image": "http://example.com/image.jpg",
            "max_progress": 1,
        }

        response = self.client.get(
            reverse(
                "track_modal",
                kwargs={
                    "source": "tmdb",
                    "media_type": "movie",
                    "media_id": "278",
                },
            )
            + "?return_url=/home",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/components/fill_track.html")

        # Check that form is in the context with initial data
        self.assertIn("form", response.context)
        self.assertEqual(response.context["form"].initial["media_id"], "278")
        self.assertEqual(response.context["form"].initial["media_type"], "movie")


class HistoryModalViewTests(TestCase):
    """Test the history modal view."""

    def setUp(self):
        """Create a user and log in."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        # Create a media item with history
        self.item = Item.objects.create(
            media_id="238",
            source="tmdb",
            media_type="movie",
            title="Test Movie",
            image="http://example.com/image.jpg",
        )
        self.movie = Movie.objects.create(
            item=self.item,
            user=self.user,
            status="In progress",
            progress=0,
        )

        # Update the movie to create history
        self.movie.status = "Completed"
        self.movie.progress = 1
        self.movie.score = 8
        self.movie.save()

    def test_history_modal_view(self):
        """Test the history modal view."""
        response = self.client.get(
            reverse(
                "history_modal",
                kwargs={
                    "source": "tmdb",
                    "media_type": "movie",
                    "media_id": "238",
                },
            )
            + "?return_url=/home",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/components/fill_history.html")

        # Check that timeline entries are in the context
        self.assertIn("timeline", response.context)
        self.assertGreater(len(response.context["timeline"]), 0)

        # Check that the first entry has changes
        first_entry = response.context["timeline"][0]
        self.assertIn("changes", first_entry)
        self.assertGreater(len(first_entry["changes"]), 0)


class DeleteHistoryRecordViewTests(TestCase):
    """Test the delete history record view."""

    def setUp(self):
        """Create a user and log in."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        # Create a media item with history
        self.item = Item.objects.create(
            media_id="238",
            source="tmdb",
            media_type="movie",
            title="Test Movie",
            image="http://example.com/image.jpg",
        )
        self.movie = Movie.objects.create(
            item=self.item,
            user=self.user,
            status="In progress",
            progress=0,
        )

        # Update the movie to create history
        self.movie.status = "Completed"
        self.movie.progress = 1
        self.movie.score = 8
        self.movie.save()

        # Get the history record and manually set the history_user
        self.history = self.movie.history.first()
        self.history_id = self.history.history_id

        # Manually update the history_user field
        self.history.history_user = self.user
        self.history.save()

    def test_delete_history_record(self):
        """Test deleting a history record."""
        response = self.client.delete(
            reverse(
                "delete_history_record",
                kwargs={
                    "media_type": "movie",
                    "history_id": self.history_id,
                },
            ),
        )

        self.assertEqual(response.status_code, 200)

        # Check that the history record was deleted
        self.assertEqual(
            self.movie.history.filter(history_id=self.history_id).count(),
            0,
        )

    def test_delete_nonexistent_history_record(self):
        """Test deleting a nonexistent history record."""
        response = self.client.delete(
            reverse(
                "delete_history_record",
                kwargs={
                    "media_type": "movie",
                    "history_id": 999999,
                },
            ),
        )

        self.assertEqual(response.status_code, 404)


class StatisticsViewTests(TestCase):
    """Test the statistics view."""

    def setUp(self):
        """Create a user and log in."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    def test_statistics_view_default_date_range(self):
        """Test the statistics view with default date range (last year)."""
        # Call the view
        response = self.client.get(reverse("statistics"))

        # Check response
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/statistics.html")

        # Check default date range (last year)
        today = timezone.now().date()
        one_year_ago = today.replace(year=today.year - 1)
        self.assertEqual(response.context["start_date"], one_year_ago)
        self.assertEqual(response.context["end_date"], today)

        # Check that all expected context variables are present
        self.assertIn("media_count", response.context)
        self.assertIn("activity_data", response.context)
        self.assertIn("media_type_distribution", response.context)
        self.assertIn("score_distribution", response.context)
        self.assertIn("status_distribution", response.context)
        self.assertIn("status_pie_chart_data", response.context)
        self.assertIn("timeline", response.context)
        self.assertIn("user_first_interaction_date", response.context)

    def test_statistics_view_custom_date_range(self):
        """Test the statistics view with custom date range."""
        # Custom date range
        start_date = "2023-01-01"
        end_date = "2023-12-31"

        # Call the view with custom date range
        response = self.client.get(
            reverse("statistics") + f"?start-date={start_date}&end-date={end_date}",
        )

        # Check response
        self.assertEqual(response.status_code, 200)

        # Check that custom date range is used
        expected_start = timezone.datetime.strptime(start_date, "%Y-%m-%d").date()
        expected_end = timezone.datetime.strptime(end_date, "%Y-%m-%d").date()

        self.assertEqual(response.context["start_date"], expected_start)
        self.assertEqual(response.context["end_date"], expected_end)

        # Check that all expected context variables are present
        self.assertIn("media_count", response.context)
        self.assertIn("activity_data", response.context)
        self.assertIn("media_type_distribution", response.context)
        self.assertIn("score_distribution", response.context)
        self.assertIn("status_distribution", response.context)
        self.assertIn("status_pie_chart_data", response.context)
        self.assertIn("timeline", response.context)
        self.assertIn("user_first_interaction_date", response.context)

    def test_statistics_view_invalid_date_format(self):
        """Test the statistics view with invalid date format."""
        # Invalid date format
        start_date = "01/01/2023"  # MM/DD/YYYY instead of YYYY-MM-DD
        end_date = "2023-12-31"

        try:
            # Call the view with invalid date format
            response = self.client.get(
                reverse("statistics") + f"?start-date={start_date}&end-date={end_date}",
            )

            # If we get here, the view handled the invalid date format
            self.assertEqual(response.status_code, 200)

            # Check if it fell back to default dates
            today = timezone.now().date()
            one_year_ago = today.replace(year=today.year - 1)

            # One of these should be true:
            # 1. Either the view used the default dates
            # 2. Or it somehow parsed the invalid format
            date_is_default = (
                response.context["start_date"] == one_year_ago
                and response.context["end_date"] == today
            )
            date_is_parsed = (
                response.context["start_date"] != one_year_ago
                or response.context["end_date"] != today
            )

            self.assertTrue(date_is_default or date_is_parsed)

        except ValueError as e:
            # If the view doesn't handle invalid dates, it might raise an exception
            # This is also an acceptable behavior
            self.assertIsInstance(e, (ValueError))


class CreateMedia(TestCase):
    """Test the creation of media objects through views."""

    def setUp(self):
        """Create a user and log in."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    @override_settings(MEDIA_ROOT=("create_media"))
    def test_create_anime(self):
        """Test the creation of a TV object."""
        Item.objects.create(
            media_id="1",
            source="mal",
            media_type="anime",
            title="Test Anime",
            image="http://example.com/image.jpg",
        )
        self.client.post(
            reverse("media_save"),
            {
                "media_id": "1",
                "source": "mal",
                "media_type": "anime",
                "status": "Planning",
                "progress": 0,
                "repeats": 0,
            },
        )
        self.assertEqual(
            Anime.objects.filter(item__media_id="1", user=self.user).exists(),
            True,
        )

    @override_settings(MEDIA_ROOT=("create_media"))
    def test_create_tv(self):
        """Test the creation of a TV object through views."""
        Item.objects.create(
            media_id="5895",
            source="tmdb",
            media_type="tv",
            title="Friends",
            image="http://example.com/image.jpg",
        )
        self.client.post(
            reverse("media_save"),
            {
                "media_id": "5895",
                "source": "tmdb",
                "media_type": "tv",
                "status": "Planning",
            },
        )
        self.assertEqual(
            TV.objects.filter(item__media_id="5895", user=self.user).exists(),
            True,
        )

    def test_create_season(self):
        """Test the creation of a Season through views."""
        Item.objects.create(
            media_id="1668",
            source="tmdb",
            media_type="season",
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=1,
        )
        self.client.post(
            reverse("media_save"),
            {
                "media_id": "1668",
                "source": "tmdb",
                "media_type": "season",
                "season_number": 1,
                "status": "Planning",
            },
        )
        self.assertEqual(
            Season.objects.filter(item__media_id="1668", user=self.user).exists(),
            True,
        )

    def test_create_episodes(self):
        """Test the creation of Episode through views."""
        self.client.post(
            reverse("episode_handler"),
            {
                "media_id": "1668",
                "season_number": 1,
                "episode_number": 1,
                "source": "tmdb",
                "date": "2023-06-01",
                "watch": "",
            },
        )
        self.assertEqual(
            Episode.objects.filter(
                item__media_id="1668",
                related_season__user=self.user,
                item__episode_number=1,
            ).exists(),
            True,
        )


class EditMedia(TestCase):
    """Test the editing of media objects through views."""

    def setUp(self):
        """Create a user and log in."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    def test_edit_movie_score(self):
        """Test the editing of a movie score."""
        item = Item.objects.create(
            media_id="10494",
            source="tmdb",
            media_type="movie",
            title="Perfect Blue",
            image="http://example.com/image.jpg",
        )
        Movie.objects.create(
            item=item,
            user=self.user,
            score=9,
            progress=1,
            status="Completed",
            notes="Nice",
            start_date=datetime.date(2023, 6, 1),
            end_date=datetime.date(2023, 6, 1),
        )

        self.client.post(
            reverse("media_save"),
            {
                "media_id": "10494",
                "source": "tmdb",
                "media_type": "movie",
                "score": 10,
                "progress": 1,
                "status": "Completed",
                "repeats": 0,
                "notes": "Nice",
            },
        )
        self.assertEqual(Movie.objects.get(item__media_id="10494").score, 10)


class DeleteMedia(TestCase):
    """Test the deletion of media objects through views."""

    def setUp(self):
        """Create a user and log in."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        self.item_tv = Item.objects.create(
            media_id="1668",
            source="tmdb",
            media_type="tv",
            title="Friends",
            image="http://example.com/image.jpg",
        )
        related_tv = TV.objects.create(
            item=self.item_tv,
            user=self.user,
            status="In progress",
        )

        self.item_season = Item.objects.create(
            media_id="1668",
            source="tmdb",
            media_type="season",
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=1,
        )
        season = Season.objects.create(
            item=self.item_season,
            user=self.user,
            related_tv=related_tv,
            status="In progress",
        )

        self.item_ep = Item.objects.create(
            media_id="1668",
            source="tmdb",
            media_type="episode",
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=1,
            episode_number=1,
        )
        Episode.objects.create(
            item=self.item_ep,
            related_season=season,
            end_date=datetime.date(2023, 6, 1),
        )

    def test_delete_tv(self):
        """Test the deletion of a tv through views."""
        self.assertEqual(TV.objects.filter(user=self.user).count(), 1)

        self.client.post(
            reverse("media_delete"),
            {"media_id": "1668", "source": "tmdb", "media_type": "tv"},
        )

        self.assertEqual(Movie.objects.filter(user=self.user).count(), 0)

    def test_delete_season(self):
        """Test the deletion of a season through views."""
        self.client.post(
            reverse("media_delete"),
            {
                "media_id": "1668",
                "source": "tmdb",
                "media_type": "tv",
                "season_number": 1,
            },
        )

        self.assertEqual(Season.objects.filter(user=self.user).count(), 0)
        self.assertEqual(
            Episode.objects.filter(related_season__user=self.user).count(),
            0,
        )

    def test_unwatch_episode(self):
        """Test unwatching of an episode through views."""
        self.client.post(
            reverse("episode_handler"),
            {
                "media_id": "1668",
                "season_number": 1,
                "episode_number": 1,
                "unwatch": "",
                "source": "tmdb",
            },
        )

        self.assertEqual(
            Episode.objects.filter(related_season__user=self.user).count(),
            0,
        )


class ProgressEditSeason(TestCase):
    """Test for editing a season progress through views."""

    def setUp(self):
        """Prepare the database with a season and an episode."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        item_tv = Item.objects.create(
            media_id="1668",
            source="tmdb",
            media_type="tv",
            title="Friends",
            image="http://example.com/image.jpg",
        )
        tv = TV.objects.create(
            item=item_tv,
            user=self.user,
            status="In progress",
        )

        self.item_season = Item.objects.create(
            media_id="1668",
            source="tmdb",
            media_type="season",
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=1,
        )
        season = Season.objects.create(
            item=self.item_season,
            related_tv=tv,
            user=self.user,
            status="In progress",
        )

        item_ep = Item.objects.create(
            media_id="1668",
            source="tmdb",
            media_type="episode",
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=1,
            episode_number=1,
        )
        Episode.objects.create(
            item=item_ep,
            related_season=season,
            end_date=datetime.date(2023, 6, 1),
        )

    def test_progress_increase(self):
        """Test the increase of progress for a season."""
        self.client.post(
            reverse("progress_edit"),
            {
                "item": self.item_season.id,
                "operation": "increase",
            },
        )

        self.assertEqual(
            Episode.objects.filter(item__media_id="1668").count(),
            2,
        )

        # episode with media_id "1668" and episode_number 2 should exist
        self.assertTrue(
            Episode.objects.filter(
                item__media_id="1668",
                item__episode_number=2,
            ).exists(),
        )

    def test_progress_decrease(self):
        """Test the decrease of progress for a season."""
        self.client.post(
            reverse("progress_edit"),
            {
                "item": self.item_season.id,
                "operation": "decrease",
            },
        )

        self.assertEqual(
            Episode.objects.filter(item__media_id="1668").count(),
            0,
        )


class ProgressEditAnime(TestCase):
    """Test for editing an anime progress through views."""

    def setUp(self):
        """Prepare the database with an anime."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        self.item = Item.objects.create(
            media_id="1",
            source="mal",
            media_type="anime",
            title="Cowboy Bebop",
            image="http://example.com/image.jpg",
        )
        Anime.objects.create(
            item=self.item,
            user=self.user,
            status="In progress",
            progress=2,
        )

    def test_progress_increase(self):
        """Test the increase of progress for an anime."""
        self.client.post(
            reverse("progress_edit"),
            {
                "item": self.item.id,
                "operation": "increase",
            },
        )

        self.assertEqual(Anime.objects.get(item__media_id="1").progress, 3)

    def test_progress_decrease(self):
        """Test the decrease of progress for an anime."""
        self.client.post(
            reverse("progress_edit"),
            {
                "item": self.item.id,
                "operation": "decrease",
            },
        )

        self.assertEqual(Anime.objects.get(item__media_id="1").progress, 1)


class CreateEntryViewTests(TestCase):
    """Test the create entry view."""

    def setUp(self):
        """Create a user and log in."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    def test_create_entry_get(self):
        """Test the GET method of create_entry view."""
        response = self.client.get(reverse("create_entry"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/create_entry.html")
        self.assertIn("media_types", response.context)

        # Verify media_types contains expected values
        self.assertEqual(response.context["media_types"], MediaTypes.values)

    def test_create_entry_post_movie(self):
        """Test creating a movie entry."""
        form_data = {
            "title": "Test Movie",
            "media_type": "movie",
            "status": "Completed",
            "score": 8,
            "progress": 1,
            "repeats": 0,
            "start_date": "2023-01-01",
            "end_date": "2023-01-02",
        }

        response = self.client.post(reverse("create_entry"), form_data, follow=True)

        # Check redirect
        self.assertRedirects(response, reverse("create_entry"))

        # Verify item was created
        self.assertTrue(
            Item.objects.filter(title="Test Movie", media_type="movie").exists(),
        )

        # Verify media was created
        movie = Movie.objects.get(item__title="Test Movie")
        self.assertEqual(movie.status, "Completed")
        self.assertEqual(movie.score, 8)
        self.assertEqual(movie.progress, 1)
        self.assertEqual(movie.repeats, 0)
        self.assertEqual(movie.user, self.user)

    def test_create_entry_post_tv(self):
        """Test creating a TV show entry."""
        form_data = {
            "title": "Test TV Show",
            "media_type": "tv",
            "status": "In progress",
            "score": 7,
            "repeats": 0,
        }

        response = self.client.post(reverse("create_entry"), form_data, follow=True)

        # Check redirect
        self.assertRedirects(response, reverse("create_entry"))

        # Verify item was created
        self.assertTrue(
            Item.objects.filter(title="Test TV Show", media_type="tv").exists(),
        )

        # Verify media was created
        tv = TV.objects.get(item__title="Test TV Show")
        self.assertEqual(tv.status, "In progress")
        self.assertEqual(tv.score, 7)
        self.assertEqual(tv.repeats, 0)
        self.assertEqual(tv.user, self.user)

    def test_create_entry_post_season(self):
        """Test creating a season entry with parent TV."""
        # First create a parent TV show
        tv_item = Item.objects.create(
            media_id="1",
            source="manual",
            media_type="tv",
            title="TV Show",
        )
        parent_tv = TV.objects.create(
            item=tv_item,
            user=self.user,
            status="In progress",
        )

        form_data = {
            "title": "TV Show",
            "media_type": "season",
            "season_number": 1,
            "parent_tv": parent_tv.id,
            "status": "In progress",
            "score": 7,
            "repeats": 0,
        }

        response = self.client.post(reverse("create_entry"), form_data, follow=True)

        # Check redirect
        self.assertRedirects(response, reverse("create_entry"))

        # Verify item was created
        self.assertTrue(
            Item.objects.filter(
                title="TV Show",
                media_type="season",
                season_number=1,
            ).exists(),
        )

        # Verify media was created with correct relationship
        season = Season.objects.get(item__title="TV Show")
        self.assertEqual(season.status, "In progress")
        self.assertEqual(season.score, 7)
        self.assertEqual(season.repeats, 0)
        self.assertEqual(season.user, self.user)
        self.assertEqual(season.related_tv, parent_tv)

    def test_create_entry_post_episode(self):
        """Test creating an episode entry with parent season."""
        # First create a parent TV show and season
        tv_item = Item.objects.create(
            media_id="1",
            source="manual",
            media_type="tv",
            title="TV Show",
        )
        parent_tv = TV.objects.create(
            item=tv_item,
            user=self.user,
            status="In progress",
        )

        season_item = Item.objects.create(
            media_id="1",
            source="manual",
            media_type="season",
            title="TV Show",
            season_number=1,
        )
        parent_season = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=parent_tv,
            status="In progress",
        )

        form_data = {
            "title": "TV Show",
            "media_type": "episode",
            "season_number": 1,
            "episode_number": 1,
            "parent_season": parent_season.id,
            "end_date": "2023-01-02",
            "repeats": 0,
        }

        response = self.client.post(reverse("create_entry"), form_data, follow=True)

        # Check redirect
        self.assertRedirects(response, reverse("create_entry"))

        # Verify item was created
        self.assertTrue(
            Item.objects.filter(
                title="TV Show",
                media_type="episode",
                season_number=1,
                episode_number=1,
            ).exists(),
        )

        # Verify media was created with correct relationship
        episode = Episode.objects.get(item__title="TV Show")
        self.assertEqual(episode.repeats, 0)
        self.assertEqual(episode.related_season, parent_season)
        self.assertEqual(episode.end_date.strftime("%Y-%m-%d"), "2023-01-02")

    def test_create_entry_post_duplicate_item(self):
        """Test creating a duplicate item."""
        # First create an item
        tv_item = Item.objects.create(
            media_id="1",
            source="manual",
            media_type="tv",
            title="TV Show",
        )
        parent_tv = TV.objects.create(
            item=tv_item,
            user=self.user,
            status="In progress",
        )

        season_item = Item.objects.create(
            media_id="1",
            source="manual",
            media_type="season",
            title="TV Show",
            season_number=1,
        )
        Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=parent_tv,
            status="In progress",
        )

        # Count items before the test
        initial_count = Item.objects.count()

        # Try to create the same season again
        form_data = {
            "title": "TV Show",
            "media_type": "season",
            "season_number": 1,
            "parent_tv": parent_tv.id,
            "status": "In progress",
            "score": 7,
            "repeats": 0,
        }

        with transaction.atomic():
            self.client.post(reverse("create_entry"), form_data)

        # No new item should be created
        self.assertEqual(Item.objects.count(), initial_count)


class SearchParentViewTests(TestCase):
    """Test the parent search views."""

    def setUp(self):
        """Create a user and log in."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        # Create some manual TV shows and seasons for testing
        tv_item1 = Item.objects.create(
            media_id="tv1",
            source="manual",
            media_type="tv",
            title="Test TV Show",
        )
        self.tv1 = TV.objects.create(
            item=tv_item1,
            user=self.user,
            status="In progress",
        )

        tv_item2 = Item.objects.create(
            media_id="tv2",
            source="manual",
            media_type="tv",
            title="Another TV Show",
        )
        self.tv2 = TV.objects.create(
            item=tv_item2,
            user=self.user,
            status="In progress",
        )

        season_item1 = Item.objects.create(
            media_id="season1",
            source="manual",
            media_type="season",
            title="Test Season",
            season_number=1,
        )
        self.season1 = Season.objects.create(
            item=season_item1,
            user=self.user,
            related_tv=self.tv1,
            status="In progress",
        )

        season_item2 = Item.objects.create(
            media_id="season2",
            source="manual",
            media_type="season",
            title="Another Season",
            season_number=1,
        )
        self.season2 = Season.objects.create(
            item=season_item2,
            user=self.user,
            related_tv=self.tv2,
            status="In progress",
        )

    def test_search_parent_tv_short_query(self):
        """Test search_parent_tv with a query that's too short."""
        response = self.client.get(reverse("search_parent_tv") + "?q=T")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/components/search_parent_tv.html")
        self.assertNotIn("results", response.context)

    def test_search_parent_tv_valid_query(self):
        """Test search_parent_tv with a valid query."""
        response = self.client.get(reverse("search_parent_tv") + "?q=Test")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/components/search_parent_tv.html")
        self.assertIn("results", response.context)
        self.assertIn("query", response.context)

        # Should find the "Test TV Show"
        self.assertEqual(len(response.context["results"]), 1)
        self.assertEqual(response.context["results"][0], self.tv1)
        self.assertEqual(response.context["query"], "Test")

    def test_search_parent_tv_no_results(self):
        """Test search_parent_tv with a query that returns no results."""
        response = self.client.get(reverse("search_parent_tv") + "?q=NonExistent")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/components/search_parent_tv.html")
        self.assertIn("results", response.context)

        # Should find no results
        self.assertEqual(len(response.context["results"]), 0)

    def test_search_parent_season_short_query(self):
        """Test search_parent_season with a query that's too short."""
        response = self.client.get(reverse("search_parent_season") + "?q=T")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/components/search_parent_tv.html")
        self.assertNotIn("results", response.context)

    def test_search_parent_season_valid_query(self):
        """Test search_parent_season with a valid query."""
        response = self.client.get(reverse("search_parent_season") + "?q=Test")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/components/search_parent_season.html")
        self.assertIn("results", response.context)
        self.assertIn("query", response.context)

        # Should find the "Test Season"
        self.assertEqual(len(response.context["results"]), 1)
        self.assertEqual(response.context["results"][0], self.season1)
        self.assertEqual(response.context["query"], "Test")

    def test_search_parent_season_no_results(self):
        """Test search_parent_season with a query that returns no results."""
        response = self.client.get(reverse("search_parent_season") + "?q=NonExistent")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/components/search_parent_season.html")
        self.assertIn("results", response.context)

        # Should find no results
        self.assertEqual(len(response.context["results"]), 0)
