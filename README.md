# Yamtrack

![App Tests](https://github.com/FuzzyGrim/Yamtrack/actions/workflows/app-tests.yml/badge.svg)
![Docker Image](https://github.com/FuzzyGrim/Yamtrack/actions/workflows/docker-image.yml/badge.svg)
![CodeFactor](https://www.codefactor.io/repository/github/fuzzygrim/yamtrack/badge)
![Codecov](https://codecov.io/github/FuzzyGrim/Yamtrack/branch/dev/graph/badge.svg?token=PWUG660120)
![GitHub](https://img.shields.io/badge/license-AGPL--3.0-blue)

Yamtrack is a self hosted media tracker for movies, tv shows, anime and manga.

You can try the app at [yamtrack.fuzzygrim.com](https://yamtrack.fuzzygrim.com) using the username `demo` and password `demo`.

## Features

- Track movies, tv shows, anime, manga and games.
- Track each season of a tv show individually and episodes watched.
- Save score, status, progress, repeats (rewatches, rereads...), start and end dates, or write a note.
- Keep a tracking history with each action with a media, such as when you added it, when you started it, when you started watching it again, etc.
- Create custom media entries, for niche media that cannot be found by the supported APIs.
- Use personal lists to organize your media for any purpose, add other members to collaborate on your lists.
- Keep up with your upcoming media with a calendar.
- Easy deployment with Docker via docker-compose with SQLite or PostgreSQL.
- Multi-users functionality allowing individual accounts with personalized tracking.
- Integration with [Jellyfin](https://jellyfin.org/), to automatically track new media watched.
- Import from [Trakt](https://trakt.tv/), [Simkl](https://simkl.com/), [MyAnimeList](https://myanimelist.net/), [AniList](https://anilist.co/) and [Kitsu](https://kitsu.app/).
- Export all your tracked media to a CSV file and import it back.

## Installing with Docker

Copy the default `docker-compose.yml` file from the repository and set the environment variables. This would use a SQlite database, which is enough for most use cases.

To start the containers run:

```bash
docker-compose up -d
```

Alternatively, if you need a PostgreSQL database, you can use the `docker-compose.postgres.yml` file.

### Environment variables

| Name            | Type   | Notes                                                                                                                                                                                           |
| --------------- | ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| TMDB_API        | String | The Movie Database API key for movies and tv shows, a default key is provided                                                                                                                   |
| TMDB_NSFW       | Bool   | Default to false, set to true to include adult content in tv and movie searches                                                                                                                 |
| TMDB_LANG       | String | TMDB metadata language, uses a Language code in ISO 639-1 e.g "en", for more specific results a country code in ISO 3166-1 can be added e.g "en-US"                                             |
| MAL_API         | String | MyAnimeList API key, for anime and manga, a default key is provided                                                                                                                             |
| MAL_NSFW        | Bool   | Default to false, set to true to include adult content in anime and manga searches from MyAnimeList                                                                                             |
| MU_NSFW         | Bool   | Default to false, set to true to include adult content in manga searches from MangaUpdates                                                                                                      |
| IGDB_ID         | String | IGDB API key for games, a default key is provided but it's recommended to get your own as it has a low rate limit                                                                               |
| IGDB_SECRET     | String | IGDB API secret for games, a default value is provided but it's recommended to get your own as it has a low rate limit                                                                          |
| IGDB_NSFW       | Bool   | Default to false, set to true to include adult content in game searches                                                                                                                         |
| SIMKL_ID        | String | Simkl API key only needed for importing media from Simkl, a default key is provided but you can get one at [Simkl Developer](https://simkl.com/settings/developer/new/custom-search/) if needed |
| SIMKL_SECRET    | String | Simkl API secret for importing media from Simkl, a default secret is provided but you can get one at [Simkl Developer](https://simkl.com/settings/developer/new/custom-search/) if needed       |
| REDIS_URL       | String | Default to redis://localhost:6379, Redis is needed for processing background tasks, set this to your redis server url                                                                           |
| SECRET          | String | [Secret key](https://docs.djangoproject.com/en/stable/ref/settings/#secret-key) used for cryptographic signing, should be a random string                                                       |
| URLS            | List   | This setting can be used to set the URLs of the app for the CSRF and ALLOWED_HOSTS settings, e.g. `https://app.example.com`                                                                     |
| ALLOWED_HOSTS   | List   | Host/domain names that this Django site can serve, e.g. `app.example.com`. See [Django documentation](https://docs.djangoproject.com/en/stable/ref/settings/#allowed-hosts) for more details.   |
| CSRF            | List   | A list of trusted origins for unsafe requests, e.g. `https://app.example.com`. See [Django documentation](https://docs.djangoproject.com/en/stable/ref/settings/#csrf-trusted-origins) for more |
| REGISTRATION    | Bool   | Default to true, set to false to disable user registration                                                                                                                                      |
| DEBUG           | Bool   | Default to false, set to true for debugging                                                                                                                                                     |
| PUID            | Int    | User ID for the app, default to 1000                                                                                                                                                            |
| PGID            | Int    | Group ID for the app, default to 1000                                                                                                                                                           |
| TZ              | String | Timezone, default to UTC                                                                                                                                                                        |
| WEB_CONCURRENCY | Int    | Number of webserver processes, default to 1 but it's recommended to have a value of [(2 x num cores) + 1](https://docs.gunicorn.org/en/latest/design.html#how-many-workers)                     |

### Environment variables for PostgreSQL

| Name        | Type   | Notes                        |
| ----------- | ------ | ---------------------------- |
| DB_HOST     | String | When not set, sqlite is used |
| DB_PORT     | Int    |                              |
| DB_NAME     | String |                              |
| DB_USER     | String |                              |
| DB_PASSWORD | String |                              |

## Local development

Clone the repository and change directory to it.

```bash
git clone https://github.com/FuzzyGrim/Yamtrack.git
cd Yamtrack
```

Install Redis or spin up a bare redis container:

```bash
docker run -d --name redis -p 6379:6379 --restart unless-stopped redis:7-alpine
```

Create a `.env` file in the root directory and add the following variables.

```bash
TMDB_API=API_KEY
MAL_API=API_KEY
IGDB_ID=IGDB_ID
IGDB_SECRET=IGDB_SECRET
SECRET=SECRET
DEBUG=True
```

Then run the following commands.

```bash
python -m pip install -U -r requirements-dev.txt
cd src
python manage.py migrate
python manage.py runserver & celery --app config worker --beat -S django --loglevel DEBUG
```

Go to: http://localhost:8000

## Donate

If you like the project and want to support it, you can donate via:

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/fuzzygrim)

