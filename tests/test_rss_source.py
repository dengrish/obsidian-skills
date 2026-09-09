#!/usr/bin/env python3
"""Offline parser, hostile-source and conditional-transport forward cases."""
from copy import deepcopy
import hashlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/feed-collect/scripts'))
import rss_source as rss

URL = 'https://example.com/feed'


def rss_feed(body):
    return ('<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:media="http://search.yahoo.com/mrss/">'
            '<channel><title>Publication</title><link>https://example.com</link>'
            + body + '</channel></rss>').encode('utf-8')


def item(body, link='https://example.com/post'):
    return '<item><title>Entry</title><link>' + link + '</link>' + body + '</item>'


class Response:
    def __init__(self, status=200, body=b'<rss/>', **headers):
        self.status = status
        self.body = io.BytesIO(body)
        self.headers = headers
        self.closed = False

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read1(self, limit):
        return self.body.read(limit)

    def close(self):
        self.closed = True


class SourceTests(unittest.TestCase):
    def test_rss_full_content_wins_over_summary_preserving_literal_source(self):
        content = '<p>First <strong>important</strong> paragraph.</p><p>Second &amp; third.</p>'
        raw = rss_feed(item('<guid isPermaLink="false">source-1</guid><dc:creator>Author</dc:creator>'
                            '<pubDate>Tue, 08 Sep 2026 08:30:00 -0700</pubDate>'
                            '<description>Short preview</description><content:encoded><![CDATA['
                            + content + ']]></content:encoded>'))
        parsed = rss.parse_feed(raw, URL)
        value = parsed['items'][0]
        self.assertEqual(parsed['title'], 'Publication')
        self.assertEqual(value['content'], content)
        self.assertEqual(value['content_scope'], 'feed_content')
        self.assertEqual(value['published_at'], '2026-09-08T15:30:00Z')
        self.assertEqual(value['authors'], ['Author'])
        self.assertEqual(value['guid'], 'source-1')
        self.assertIn('First **important** paragraph.\n\nSecond &amp; third.', value['markdown'])
        self.assertNotIn('Short preview', value['markdown'])

    def test_summary_and_missing_dates_never_become_full_article_or_current_time(self):
        values = rss.parse_feed(rss_feed(item('<description><![CDATA[<p>Preview only</p>]]></description>')), URL)
        value = values['items'][0]
        self.assertEqual(value['content_scope'], 'summary_only')
        self.assertIsNone(value['published_at'])
        self.assertIsNone(value['updated_at'])
        self.assertIn('publication_date_unavailable', value['diagnostics'])

    def test_atom_namespaced_xhtml_nested_xml_base_and_fallback_author(self):
        raw = b'''<feed xmlns="http://www.w3.org/2005/Atom" xml:base="https://example.com/blog/">
        <title>Atom publication</title><author><name>Publisher</name></author>
        <link rel="alternate" href="./"/><entry xml:base="2026/">
        <id>tag:example.com,2026:1</id><title>Article</title><link href="entry#intro"/>
        <updated>2026-09-08T09:00:00+02:00</updated><content type="xhtml">
        <div xmlns="http://www.w3.org/1999/xhtml" xml:base="../../assets/">
        <h2>Details</h2><p>Read <a href="report.pdf">report</a>.</p><img src="chart.png" alt="Chart"/>
        </div></content></entry></feed>'''
        parsed = rss.parse_feed(raw, URL)
        value = parsed['items'][0]
        self.assertEqual(value['canonical_url'], 'https://example.com/blog/2026/entry')
        self.assertEqual(value['guid'], 'tag:example.com,2026:1')
        self.assertEqual(value['authors'], ['Publisher'])
        self.assertEqual(value['updated_at'], '2026-09-08T07:00:00Z')
        self.assertIsNone(value['published_at'])
        self.assertEqual(value['content_type'], 'xhtml')
        self.assertIn('#### Details', value['markdown'])
        self.assertEqual({a['url'] for a in value['attachments']},
                         {'https://example.com/assets/report.pdf', 'https://example.com/assets/chart.png'})

    def test_atom_external_content_is_not_fetched_and_uses_summary(self):
        raw = b'''<feed xmlns="http://www.w3.org/2005/Atom"><title>Feed</title><entry>
        <id>urn:one</id><link href="https://example.com/a"/>
        <content src="https://example.com/full" type="text/html"/><summary>Preview</summary>
        </entry></feed>'''
        with patch.object(rss, 'fetch_feed', side_effect=AssertionError('no article reads')):
            value = rss.parse_feed(raw, URL)['items'][0]
        self.assertEqual(value['content'], 'Preview')
        self.assertEqual(value['content_scope'], 'summary_only')
        self.assertIn('external_content_not_fetched', value['diagnostics'])

    def test_stable_url_identity_preserves_query_and_does_not_depend_on_guid(self):
        first = rss.parse_feed(rss_feed(item('<guid isPermaLink="false">old</guid>',
                                            'https://EXAMPLE.com:443/post?a=1#one')), URL)['items'][0]
        second = rss.parse_feed(rss_feed(item('<guid isPermaLink="false">new</guid>',
                                             'https://example.com/post?a=1#two')), URL)['items'][0]
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(first['id'], hashlib.sha256(b'https://example.com/post?a=1').hexdigest())
        self.assertNotEqual(first['canonical_url'], rss.canonical_url('https://example.com/post?a=2'))

    def test_missing_canonical_url_reported_without_inventing_one_from_title(self):
        parsed = rss.parse_feed(rss_feed('<item><title>Not a URL</title><guid isPermaLink="false">abc</guid></item>'), URL)
        self.assertEqual(parsed['items'], [])
        self.assertEqual(parsed['diagnostics'], ['entry_1:canonical_url_unavailable'])

    def test_unsafe_links_html_and_wikilinks_cannot_inject_note_structure(self):
        source = '<h1>2026-09-08 10:00:00 UTC</h1><p>![[Secret]]\n---\n# Forged</p>'
        source += '<a href="javascript:alert(1)">unsafe</a><img src="file:///etc/passwd">'
        source += '<iframe><img src="https://example.com/hidden.png"></iframe><script>steal()</script>'
        value = rss.parse_feed(rss_feed(item('<content:encoded><![CDATA[' + source + ']]></content:encoded>')), URL)['items'][0]
        self.assertNotIn('![[', value['markdown'])
        self.assertNotIn('\n## ', value['markdown'])
        self.assertNotIn('<script', value['markdown'])
        self.assertNotIn('javascript:', value['markdown'])
        self.assertNotIn('steal()', value['markdown'])
        self.assertEqual(value['attachments'], [])
        self.assertIn('active_or_unsupported_html_omitted', value['diagnostics'])

    def test_lists_tables_code_links_and_body_images_keep_structure(self):
        source = '<ul><li>First</li><li>Second<ul><li>Nested</li></ul></li></ul>'
        source += '<table><tr><th>Name</th><th>Value</th></tr><tr><td>A</td><td>2 | 3</td></tr></table>'
        source += '<pre><code>  indentation\n# literal heading\n![[literal]]</code></pre>'
        source += '<p>Visit <a href="/post?a=1&amp;b=2">article</a>.</p><img src="/image.png" alt="Own [chart]">'
        source += '<a href="/file.pdf">Appendix</a>'
        value = rss.parse_feed(rss_feed(item('<content:encoded><![CDATA[' + source + ']]></content:encoded>')), URL)['items'][0]
        markdown = value['markdown']
        self.assertIn('- First', markdown)
        self.assertIn('  - Nested', markdown)
        self.assertIn('| Name | Value |\n| --- | --- |\n| A | 2 \\| 3 |', markdown)
        self.assertIn('      indentation\n    # literal heading\n    ![[literal]]', markdown)
        self.assertIn('[article](https://example.com/post?a=1&b=2)', markdown)
        self.assertEqual({a['kind'] for a in value['attachments']}, {'image', 'pdf'})
        self.assertNotIn('![Image', markdown)

    def test_only_entry_own_media_and_enclosures_not_publication_logo(self):
        raw = rss_feed('<image><url>https://example.com/logo.png</url></image>' + item(
            '<media:content url="/own.jpg" medium="image"/><enclosure url="/report.pdf" type="application/pdf"/>'))
        value = rss.parse_feed(raw, URL)['items'][0]
        self.assertEqual({a['url'] for a in value['attachments']},
                         {'https://example.com/own.jpg', 'https://example.com/report.pdf'})
        self.assertTrue(all(a['markdown'] in value['markdown'] for a in value['attachments']))

    def test_functional_http_links_and_fragments_do_not_enable_http_downloads(self):
        source = '<p><a href="http://example.org:80/a#section">Old reference</a> '
        source += '<a href="https://example.com/a?q=1#part2">New reference</a></p>'
        source += '<img src="http://example.org/image.png" alt="Old diagram">'
        value = rss.parse_feed(rss_feed(item('<content:encoded><![CDATA[' + source + ']]></content:encoded>')), URL)['items'][0]
        self.assertIn('[Old reference](http://example.org/a#section)', value['markdown'])
        self.assertIn('[New reference](https://example.com/a?q=1#part2)', value['markdown'])
        self.assertIn('(http://example.org/image.png)', value['markdown'])
        self.assertEqual(value['attachments'], [])
        self.assertIn('http_image_not_archived', value['diagnostics'])

    def test_quoted_voice_ordered_numbering_and_merged_table_cells_remain_explicit(self):
        source = '<blockquote><p>The quoted claim.</p><p>The quoted limitation.</p></blockquote>'
        source += '<ol start="3"><li>Third point</li><li value="7">Seventh point</li></ol>'
        source += '<table><tr><th colspan="2">Both columns</th></tr><tr><td>Left</td><td>Right</td></tr></table>'
        value = rss.parse_feed(rss_feed(item('<content:encoded><![CDATA[' + source + ']]></content:encoded>')), URL)['items'][0]
        self.assertIn('> The quoted claim.\n>\n> The quoted limitation.', value['markdown'])
        self.assertIn('3. Third point\n7. Seventh point', value['markdown'])
        self.assertIn('Row 1, cell 1 (colspan 2, rowspan 1): Both columns', value['markdown'])
        self.assertIn('Row 2, cell 2 (colspan 1, rowspan 1): Right', value['markdown'])
        self.assertNotIn('| Both columns |', value['markdown'])
        self.assertIn('table_spans_flattened', value['diagnostics'])

    def test_feed_thumbnails_tracking_pixels_and_explicit_missing_image_ui_are_not_archived(self):
        source = '<img width="1" height="1" src="https://example.com/track.gif">'
        source += '<img src="/img/missing-image.png"><img src="/actual.png">'
        raw = rss_feed(item('<media:thumbnail url="https://example.com/preview.jpg"/>'
                            '<content:encoded><![CDATA[' + source + ']]></content:encoded>'))
        value = rss.parse_feed(raw, URL)['items'][0]
        self.assertEqual([a['url'] for a in value['attachments']], ['https://example.com/actual.png'])
        self.assertIn('Source image unavailable.', value['markdown'])
        self.assertTrue({'media_thumbnail_not_archived', 'tracking_sized_image_omitted',
                         'unavailable_source_image_placeholder'} <= set(value['diagnostics']))

    def test_first_code_block_preserves_indentation_and_internal_blank_lines(self):
        source = '<div><pre><code> first\n\n\nlast</code></pre><p>Next paragraph</p></div>'
        value = rss.parse_feed(rss_feed(item('<content:encoded><![CDATA[' + source + ']]></content:encoded>')), URL)['items'][0]
        self.assertTrue(value['markdown'].startswith('     first\n    \n    \n    last'))
        self.assertIn('\n\nNext paragraph', value['markdown'])

    def test_xml_dtd_entities_utf16_and_depth_are_rejected(self):
        evil = '<!DOCTYPE rss [<!ENTITY a "boom">]><rss version="2.0"><channel>&a;</channel></rss>'
        for raw in (evil.encode('utf-8'), evil.encode('utf-16')):
            with self.subTest(raw=raw[:20]), self.assertRaisesRegex(rss.RSSSourceError, 'dtd_or_entity'):
                rss.parse_feed(raw, URL)
        raw = rss_feed('<x>' * 70 + '</x>' * 70)
        with self.assertRaisesRegex(rss.RSSSourceError, 'structure_limit'):
            rss.parse_feed(raw, URL)

    def test_entry_bounds_malformed_xml_and_naive_dates(self):
        with patch.object(rss, 'ENTRY_LIMIT', 1), self.assertRaisesRegex(rss.RSSSourceError, 'entry_limit'):
            rss.parse_feed(rss_feed(item('') + item('')), URL)
        with self.assertRaisesRegex(rss.RSSSourceError, 'invalid_feed_xml'):
            rss.parse_feed(b'<rss', URL)
        value = rss.parse_feed(rss_feed(item('<pubDate>2026-09-08T10:00:00</pubDate>')), URL)['items'][0]
        self.assertIsNone(value['published_at'])
        self.assertIn('invalid_published_at', value['diagnostics'])


class AcquisitionTests(unittest.TestCase):
    def run_fetch(self, responses, **kwargs):
        calls, connections = [], []
        def request(host, path, addresses, deadline, *, extra_headers=None):
            calls.append((host, path, deepcopy(extra_headers)))
            connection = Mock()
            connections.append(connection)
            return connection, responses.pop(0), None
        with patch.object(rss.feed_media, '_target', side_effect=lambda url: (
                rss.urllib.parse.urlsplit(url).hostname, rss.urllib.parse.urlsplit(url).path, ['public-pinned-address'])), \
                patch.object(rss.feed_media, '_request', side_effect=request):
            result = rss.fetch_feed(URL, **kwargs)
        self.assertTrue(all(connection.close.called for connection in connections))
        return result, calls

    def test_conditional_not_modified_does_not_read_body(self):
        response = Response(304, ETag='"version1"')
        response.read1 = Mock(side_effect=AssertionError('must not read a 304 body'))
        result, calls = self.run_fetch([response], etag='"version1"')
        self.assertEqual(result['status'], 'not_modified')
        self.assertIsNone(result['body'])
        self.assertEqual(result['requests'], 1)
        self.assertEqual(result['bytes'], 0)
        self.assertEqual(calls[0][2]['If-None-Match'], '"version1"')
        self.assertTrue(response.closed)

    def test_modified_has_exact_bytes_and_new_validators(self):
        body = rss_feed(item('<description>New</description>'))
        response = Response(body=body, ETag='"v2"', **{'Content-Length': str(len(body)), 'Last-Modified': 'Tue, 08 Sep 2026 15:00:00 GMT'})
        result, calls = self.run_fetch([response], etag='"v1"', last_modified='Mon, 07 Sep 2026 15:00:00 GMT')
        self.assertEqual(result['body'], body)
        self.assertEqual(result['etag'], '"v2"')
        self.assertEqual(result['bytes'], len(body))
        self.assertIn('If-Modified-Since', calls[0][2])

    def test_redirects_are_revalidated_and_cross_origin_drops_validators(self):
        result, calls = self.run_fetch([Response(302, Location='https://other.example/feed'), Response(body=b'<feed/>')], etag='"private-validator"')
        self.assertEqual(result['final_url'], 'https://other.example/feed')
        self.assertEqual(result['requests'], 2)
        self.assertNotIn('If-None-Match', calls[1][2])
        with self.assertRaisesRegex(rss.RSSSourceError, 'invalid_public_feed_url'):
            self.run_fetch([Response(302, Location='https://127.0.0.1/feed')])

    def test_same_origin_changed_resource_drops_validator_and_failures_count_attempts(self):
        result, calls = self.run_fetch([Response(302, Location='/different-feed'), Response()], etag='"old-resource"')
        self.assertNotIn('If-None-Match', calls[1][2])
        with self.assertRaises(rss.RSSSourceError) as failure:
            self.run_fetch([Response(302, Location='/different-feed'), Response(403)])
        self.assertEqual(failure.exception.requests, 2)

    def test_limits_compression_http_errors_and_unsolicited_304(self):
        fixtures = [(Response(body=b'123456'), {'max_bytes': 5}, 'too_large'),
                    (Response(**{'Content-Length': '999'}), {'max_bytes': 5}, 'oversized_length'),
                    (Response(**{'Content-Encoding': 'gzip'}), {}, 'compressed'),
                    (Response(401), {}, 'http_401'), (Response(304), {}, 'unsolicited')]
        for response, options, error in fixtures:
            with self.subTest(error=error), self.assertRaisesRegex(rss.RSSSourceError, error):
                self.run_fetch([response], **options)
        with self.assertRaisesRegex(rss.RSSSourceError, 'redirect_limit'):
            self.run_fetch([Response(302, Location='/other')], max_requests=1)

    def test_transport_protocol_errors_become_bounded_source_errors(self):
        with patch.object(rss.feed_media, '_target', return_value=('example.com', '/', [])), \
                patch.object(rss.feed_media, '_request', side_effect=rss.http.client.BadStatusLine('invalid')):
            with self.assertRaisesRegex(rss.RSSSourceError, 'feed_request_failed'):
                rss.fetch_feed(URL)

    def test_stalled_dns_cannot_overrun_deadline_or_later_issue_http(self):
        release = rss.threading.Event()
        def resolver(url):
            release.wait(1)
            return ('example.com', '/', [])
        with patch.object(rss.feed_media, '_target', side_effect=resolver), \
                patch.object(rss.feed_media, '_request', side_effect=AssertionError('no late HTTP')) as request:
            try:
                with self.assertRaisesRegex(rss.RSSSourceError, 'resolver_timeout') as failure:
                    rss.fetch_feed(URL, timeout=0.01)
                self.assertEqual(failure.exception.requests, 0)
                self.assertEqual(request.call_count, 0)
            finally:
                release.set()

    def test_bad_validator_and_nonpublic_url_fail_before_any_socket(self):
        with patch.object(rss.feed_media, '_target', side_effect=AssertionError('no network')):
            for url in ('http://example.com/feed', 'https://user:password@example.com/feed',
                        'https://localhost/feed', 'https://[::1]/feed', 'https://10.1.2.3/feed'):
                with self.subTest(url=url), self.assertRaises(rss.RSSSourceError):
                    rss.fetch_feed(url)
            with self.assertRaisesRegex(rss.RSSSourceError, 'cache_validator'):
                rss.fetch_feed(URL, etag='bad\r\nAuthorization: secret')

    def test_optional_transport_headers_allow_only_conditionals_and_accept(self):
        with patch.object(rss.feed_media.socket, 'socket', side_effect=AssertionError('no socket')):
            for headers in ({'Authorization': 'secret'}, {'Cookie': 'secret'},
                            {'Host': 'other'}, {'If-None-Match': 'bad\nheader'}):
                with self.subTest(headers=headers), self.assertRaisesRegex(rss.feed_media.MediaError, 'request_header'):
                    rss.feed_media._request('example.com', '/', [], 99999, extra_headers=headers)
        wire, connection, response = Mock(), Mock(), Mock()
        connection.getresponse.return_value = response
        with patch.object(rss.feed_media.socket, 'socket', return_value=wire), \
                patch.object(rss.feed_media.ssl, 'create_default_context') as tls, \
                patch.object(rss.feed_media.http.client, 'HTTPConnection', return_value=connection):
            tls.return_value.wrap_socket.return_value = wire
            rss.feed_media._request('example.com', '/', [(2, 1, 6, '', ('93.184.216.34', 443))],
                                    rss.time.monotonic() + 30, extra_headers={'If-None-Match': '"v1"'})
        headers = connection.request.call_args.kwargs['headers']
        self.assertEqual(headers['If-None-Match'], '"v1"')
        self.assertEqual(headers['Host'], 'example.com')
        self.assertEqual(headers['Accept-Encoding'], 'identity')
        self.assertNotIn('Authorization', headers)
        self.assertNotIn('Cookie', headers)


if __name__ == '__main__':
    unittest.main()
