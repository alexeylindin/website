from dataclasses import dataclass
import datetime
import json
import logging
import bisect
from typing import Dict, List, Union
from uuid import UUID
from django import views
from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.views.decorators.cache import cache_control
from django.shortcuts import render, get_object_or_404, redirect
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.core.paginator import Paginator, Page
from django.core.management import call_command
from django.urls import reverse
from django.db.models import query
from algoliasearch.search_client import SearchClient

from books import serializers
from books.templatetags.books_extras import to_human_language

from .models import Book, BookStatus, LinkType, Person, Tag, Language

active_books = Book.objects.filter(
    status=BookStatus.ACTIVE).prefetch_related('authors')

logger = logging.getLogger(__name__)

TAGS_TO_SHOW_ON_MAIN_PAGE = [
    'Сучасная проза',
    'Класікі беларускай літаратуры',
    'Дзецям і падлеткам',
]

BOOKS_PER_PAGE = 16


@dataclass
class Article:
    '''Data related to a single article.'''
    # Example: 'Як выкласці аўдыякнігу'
    title: str
    # Example: jak-vyklasci-audyjaknihu
    slug: str
    # Example: 'Гэта артыкула пра бла-бла'
    short_description: str
    # Example: how-to-publish-audiobook.html
    template: str


ARTICLES: List[Article] = [
    Article(
        title='Як выкласці аўдыякнігу',
        short_description=
        'Гайд пра тое, як лепей распаўсюдзіць аўдыякнігу на беларускай мове.',
        slug='jak-vyklasci-audyjaknihu',
        template='how-to-publish-audiobook.html'),
    Article(title='База даных audiobooks.by',
            short_description=
            'Дзе знайсці і як карыстацца базай даных сайта audiobooks.by',
            slug='baza-danych-audiobooksby',
            template='audiobooksby-database.html'),
    Article(title='Гайд па вокладках аўдыякніг',
            short_description=
            'Як зрабіць добрыя вокладкі аўдыякніг: фармат, памеры, змест.',
            slug='hajd-pa-vokladkach-audyjaknih',
            template='covers-guide.html'),
]


def maybe_filter_links(books_query: query.QuerySet,
                       request: HttpRequest) -> query.QuerySet:
    '''
    Filters given Book query set to keep only the books that have at least one
    link of type passed as `links` url param. For example /catalog?links=knihi_com
    should show only books that hosted on knihi.com.
    '''
    links = request.GET.get('links')
    if links is None:
        return books_query
    return books_query.filter(
        narrations__links__url_type__name__in=links.split(','))


def index(request: HttpRequest) -> HttpResponse:
    '''Index page, starting page'''
    # Getting all Tags and creating querystring objects for each to pass to template
    tags_to_render = []
    for tag in Tag.objects.filter(name__in=TAGS_TO_SHOW_ON_MAIN_PAGE):
        tags_to_render.append({
            'name':
            tag.name,
            'slug':
            tag.slug,
            'books':
            active_books.filter(tag=tag.id).order_by('-date'),
        })

    context = {
        'promo_books': active_books.filter(promoted=True),
        'recently_added_books': active_books.order_by('-date')[:6],
        'tags_to_render': tags_to_render,
    }

    return render(request, 'books/index.html', context)


def get_query_params_without(request: HttpRequest, param: str) -> str:
    '''Returns query string without given param'''
    params = request.GET.copy()
    if param in params:
        params.pop(param)
    if len(params) == 0:
        return ''
    return '?' + params.urlencode()


def catalog(request: HttpRequest, tag_slug: str = '') -> HttpResponse:
    '''Catalog page for specific tag or all books'''

    page = request.GET.get('page')
    tags = Tag.objects.all()
    filtered_books = maybe_filter_links(active_books, request).distinct()

    tag = None
    if tag_slug:
        # get selected tag id
        tag = tags.filter(slug=tag_slug).first()
        # pagination for the books by tag
        filtered_books = filtered_books.filter(tag=tag.id)

    lang = request.GET.get('lang')
    if lang:
        filtered_books = filtered_books.filter(
            narrations__language=lang.upper())

    language_options = [('', 'любая', lang == None)]
    for available_lang in Language.values:
        language_options.append(
            (available_lang.lower(), to_human_language(available_lang),
             lang == available_lang.lower()))

    paid = request.GET.get('paid')
    if paid is not None:
        filtered_books = filtered_books.filter(
            narrations__paid=(request.GET.get('paid') == 'true'))

    price_options = [
        ('', 'усе', paid is None),
        ('true', 'платныя', paid == 'true'),
        ('false', 'бясплатныя', paid == 'false'),
    ]

    sorted_books = filtered_books.order_by('-date')
    paginator = Paginator(sorted_books, BOOKS_PER_PAGE)
    paged_books: Page = paginator.get_page(page)

    def related_page(page: int) -> str:
        params = request.GET.copy()
        if page == 1:
            params.pop('page')
        else:
            params['page'] = page
        return request.path + ('?' if len(params) > 0 else
                               '') + params.urlencode()

    related_pages = {
        'has_other': paged_books.has_other_pages(),
    }
    if paged_books.has_previous():
        related_pages['first'] = related_page(1)
        related_pages['prev'] = related_page(
            paged_books.previous_page_number())
    if paged_books.has_next():
        related_pages['last'] = related_page(paginator.num_pages)
        related_pages['next'] = related_page(paged_books.next_page_number())

    context = {
        'books': paged_books,
        'related_pages': related_pages,
        'selected_tag': tag,
        'tags': tags,
        'query_params': get_query_params_without(request, 'page'),
        'language_options': language_options,
        'price_options': price_options,
    }
    return render(request, 'books/catalog.html', context)


def book_detail(request: HttpRequest, slug: str) -> HttpResponse:
    '''Detailed book page'''
    book = get_object_or_404(Book, slug=slug)

    # Determine if all narrations for the given book are of the same
    # language. That determine whether we show language once at the top
    # or separately for each narration.
    single_language = None
    narrations = book.narrations.all()
    if len(narrations) > 0:
        single_language = narrations[0].language
        for narration in narrations:
            if narration.language != single_language:
                single_language = None
                break

    context = {
        'book': book,
        'authors': book.authors.all(),
        'translators': book.translators.all(),
        'narrations': book.narrations.all(),
        'tags': book.tag.all(),
        'single_language': single_language,
        'show_russian_title': single_language == Language.RUSSIAN,
    }

    return render(request, 'books/book-detail.html', context)


def person_detail(request: HttpRequest, slug: str) -> HttpResponse:
    '''Detailed book page'''

    # TODO: remove it later if all good
    # identified_person = get_object_or_404(Person, slug=slug)

    # Prefetch all books in the relationships
    person = Person.objects.prefetch_related(
        'books_authored', 'books_translated',
        'narrations').filter(slug=slug).first()

    if person:
        author = maybe_filter_links(
            person.books_authored.all().filter(status=BookStatus.ACTIVE),
            request)
        translator = maybe_filter_links(
            person.books_translated.all().filter(status=BookStatus.ACTIVE),
            request)
        narrations = person.narrations.all().filter()
        if request.GET.get('links'):
            links = request.GET.get('links').split(',')
            narrations = narrations.filter(links__url_type__name__in=links)

        narrated_books = [
            item.book for item in narrations
            if item.book.status == BookStatus.ACTIVE
        ]

        context = {
            'person': person,
            'author': author,
            'translator': translator,
            'narrations': narrated_books,
        }

        return render(request, 'books/person.html', context)

    else:
        pass  #TODO: implement 404 page


def search(request: HttpRequest) -> HttpResponse:
    '''Search results'''
    query = request.GET.get('query')

    if query:
        client = SearchClient.create(settings.ALGOLIA_APPLICATION_ID,
                                     settings.ALGOLIA_SEARCH_KEY)
        index = client.init_index(settings.ALGOLIA_INDEX)
        # Response:
        # ttps://www.algolia.com/doc/guides/building-search-ui/going-further/backend-search/in-depth/understanding-the-api-response/
        hits = index.search(query, {'hitsPerPage': 100})['hits']

        # Load all models, books and people returned from algolia.
        people_ids: List[str] = []
        books_ids: List[str] = []
        for hit in hits:
            if hit['model'] == 'person':
                people_ids.append(hit['objectID'])
            elif hit['model'] == 'book':
                books_ids.append(hit['objectID'])
            else:
                logger.warning('Got unexpected model from search %s',
                               hit['model'],
                               extra=hit)
        loaded_models: Dict[str, Union[Person, Book]] = {}
        for person in Person.objects.all().filter(uuid__in=people_ids):
            loaded_models[str(person.uuid)] = person
        for book in Book.objects.all().prefetch_related('authors').filter(
                uuid__in=books_ids):
            loaded_models[str(book.uuid)] = book

        # Build search result list in the same order as returned by algolia.
        # So that most relevant are shown first.
        search_results = [{
            'type': hit['model'],
            'object': loaded_models[hit['objectID']]
        } for hit in hits]

        context = {
            'results': search_results[:50],
            'query': query,
        }

    else:
        context = {
            'results': [],
            'query': '',
        }

    return render(request, 'books/search.html', context)


def about(request: HttpRequest) -> HttpResponse:
    '''About us page containing info about the website and the team.'''
    people = [
        ('Мікіта', 'images/member-mikita.jpg'),
        ('Яўген', 'images/member-jauhen.jpg'),
        ('Павал', 'images/member-paval.jpg'),
        ('Алесь', 'images/member-ales.jpg'),
        # ('Наста', 'images/member-nasta.jpg'),
        ('Алёна', 'images/member-alena.jpg'),
        ('Юры', 'images/member-jura.jpg'),
        ('Андрэй', 'images/member-andrey.jpg'),
        ('Вікторыя', 'images/member-andrey.jpg'),
        ('Жэня', 'images/member-andrey.jpg'),
    ]
    context = {
        'team_members': people,
        'books_count': Book.objects.count(),
    }
    return render(request, 'books/about.html', context)


def push_data_to_algolia(request: HttpRequest) -> HttpResponse:
    '''
    HTTP hook that pushes all data from DB to algolia.
    It's called hourly by an appengine job.
    '''
    call_command('push_data_to_algolia')
    return HttpResponse(status=204)


def page_not_found(request: HttpRequest) -> HttpResponse:
    '''Helper method to test 404 page rendering locally, where using real 404 shows stack trace.'''
    return views.defaults.page_not_found(request, None)


def robots_txt(request: HttpRequest) -> HttpResponse:
    '''
    Serve robots.txt
    https://developers.google.com/search/docs/advanced/robots/intro?hl=en
    '''
    context = {
        'host': request.get_host(),
        'protocol': 'https' if request.is_secure() else 'http'
    }
    return render(request, 'robots.txt', context)


def sitemap(request: HttpRequest) -> HttpResponse:
    '''
    Serve sitemap in text format.
    https://developers.google.com/search/docs/advanced/sitemaps/overview?hl=en
    '''
    pages: List[str] = ['/', '/about', '/catalog', '/articles']
    for article in ARTICLES:
        pages.append(reverse('single-article', args=(article.slug, )))
    for book in active_books:
        pages.append(reverse('book-detail-page', args=(book.slug, )))
    for person in Person.objects.all():
        pages.append(reverse('person-detail-page', args=(person.slug, )))
    for tag in Tag.objects.all():
        pages.append(reverse('catalog-for-tag', args=(tag.slug, )))
    domain = 'https' if request.is_secure() else 'http'
    domain = domain + '://' + request.get_host()
    result = '\n'.join(domain + page for page in pages)
    return HttpResponse(result, content_type='text/plain')


def redirect_to_first_article(request: HttpRequest) -> HttpRequest:
    '''Redirects to the first article'''
    return redirect(reverse('single-article', args=(ARTICLES[0].slug, )))


def single_article(request: HttpRequest, slug: str) -> HttpResponse:
    '''Serve an article'''
    for article in ARTICLES:
        if article.slug == slug:
            return render(request, f'books/articles/{article.template}', {
                'article': article,
                'all_articles': ARTICLES,
            })
    return views.defaults.page_not_found(request, None)


DATA_JSON_FILE = 'tmp_data.json'


class UUIDEncoder(json.JSONEncoder):

    def default(self, obj):
        if isinstance(obj, UUID):
            # if the obj is uuid, we simply return the value of uuid
            return str(obj)
        return json.JSONEncoder.default(self, obj)


def generate_data_json(request: HttpRequest) -> HttpResponse:
    '''
    HTTP hook that triggers generation of data.json file which
    will be cached and served by another handler.
    '''
    data: Dict = {
        'books':
        serializers.BookSimpleSerializer(
            Book.objects.prefetch_related('narrations').all(), many=True).data,
        'people':
        serializers.PersonSimpleSerializer(Person.objects.all(),
                                           many=True).data,
        'link_types':
        serializers.LinkTypeSimpleSerializer(LinkType.objects.all(),
                                             many=True).data,
        'tags':
        serializers.TagSerializer(Tag.objects.all(), many=True).data
    }
    if default_storage.exists(DATA_JSON_FILE):
        default_storage.delete(DATA_JSON_FILE)

    data_str = json.dumps(data, ensure_ascii=False, indent=4, cls=UUIDEncoder)
    default_storage.save(DATA_JSON_FILE, ContentFile(data_str.encode('utf-8')))
    return HttpResponse(status=204)


@cache_control(max_age=60 * 60 * 24)
def get_data_json(request: HttpRequest) -> HttpResponse:
    '''
    Returns cached data.json that was generated by the generate_data_json
    handler.
    '''
    content = ''
    if default_storage.exists(DATA_JSON_FILE):
        with default_storage.open(DATA_JSON_FILE, 'r') as f:
            content = f.read()
    return HttpResponse(
        content,
        content_type='application/json',
        headers={
            # Allow accessing data.json from JS.
            'Access-Control-Allow-Origin': '*',
        })


def update_read_by_author_tag(request: HttpRequest) -> HttpResponse:
    '''
    HTTP hook that triggers update of 'Read by author tag'.
    '''
    read_by_author_tag = Tag.objects.filter(slug='cytaje-autar').first()
    if read_by_author_tag is None:
        return HttpResponse(status=500,
                            content='Tag cytaje-autar is missing from DB')
    books = Book.objects.prefetch_related('tag', 'narrations').all()
    book: Book
    read_by_author_tag.books.clear()
    for book in books:
        authors = set(book.authors.all())
        for narration in book.narrations.all():
            for narrator in narration.narrators.all():
                if narrator in authors:
                    read_by_author_tag.books.add(book)
    read_by_author_tag.save()
    return HttpResponse(status=204)


def birthdays(request: HttpRequest) -> HttpResponse:
    '''Birthday page'''
    now = datetime.datetime.now()
    people = list(
        Person.objects.filter(date_of_birth__isnull=False).order_by(
            'date_of_birth__month', 'date_of_birth__day'))
    days = [p.date_of_birth.month * 31 + p.date_of_birth.day for p in people]
    ind = bisect.bisect_left(days, now.month * 31 + now.day)
    people = people[ind:] + people[:ind]

    people_with_info = []
    for person in people[:30]:
        next_birthday = datetime.date(now.year, person.date_of_birth.month,
                                      person.date_of_birth.day)
        if next_birthday < now.date():
            next_birthday = datetime.date(now.year + 1,
                                          person.date_of_birth.month,
                                          person.date_of_birth.day)
        people_with_info.append({
            'date_of_birth':
            person.date_of_birth,
            'person':
            person,
            'age':
            now.year - person.date_of_birth.year,
            'days_left': (next_birthday - now.date()).days,
            'stats':
            '%d - %d - %d' % (
                person.books_authored.count(),
                person.books_translated.count(),
                person.narrations.count(),
            ),
        })
    context = {
        'people_with_info': people_with_info,
    }
    return render(request, 'books/stats/birthdays.html', context)