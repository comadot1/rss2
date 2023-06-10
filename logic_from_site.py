# -*- coding: utf-8 -*-
#########################################################
# python
import traceback
import re
import logging
from time import sleep
import os

# third-party
import requests
from lxml import html
from xml.sax.saxutils import escape, unescape

# sjva 공용
from framework import app, db, scheduler, path_data, py_urllib2, py_urllib#, celery
from framework.job import Job
from framework.util import Util
from system.logic import SystemLogic

# 패키지
from .plugin import logger, package_name
from .model import ModelSetting
#########################################################


#토렌트퐁 Accept 2개 필요함
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/71.0.3578.98 Safari/537.36',
    'Accept' : 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language' : 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
    'Referer' : '',
#    'Cookie' :'over18=1'
} 



class LogicFromSite(object):
    proxyes = None
    session = requests.Session()
    

    # 스케쥴러에서도 호출할 수 있고, 직접 RSS에서도 호출할수 있다
    @staticmethod
    def get_list(site_instance, board, query=None, page=1, max_id=0, max_count=999, scheduler_instance=None):
        try:
            LogicFromSite.set_proxy(scheduler_instance)
            if 'LOGIN_INFO' in site_instance.info:
                login_dict = site_instance.info['LOGIN_INFO']
                loginurl = login_dict['LOGIN_URL']
                logindata = {
                    'mb_id': login_dict['USERNAME'],
                    'mb_password': login_dict['PASSWORD']
                }
                response = LogicFromSite.session.post(loginurl, data=logindata)
                if response.status_code == 200:
                    logger.debug('로그인 성공')
                else:
                    logger.debug('로그인 실패')
            max_page = int(page) if page is not None else 1
            xpath_list_tag_name = 'XPATH_LIST_TAG'
            if 'BOARD_LIST' in site_instance.info:
                tmp = board.split('&')[0]
                if board.split('&')[0] in site_instance.info['BOARD_LIST']:
                    xpath_list_tag_name = site_instance.info['BOARD_LIST'][tmp]
            xpath_dict = site_instance.info[xpath_list_tag_name]
            
            
            bbs_list = LogicFromSite.__get_bbs_list(site_instance, board, max_page, max_id, xpath_dict, is_test=(max_count!=999))
            count = 0
            for item in bbs_list:
                try:
                    cookie = site_instance.info['COOKIE'] if 'COOKIE' in site_instance.info else None
                    selenium_tag = None
                    if 'USE_SELENIUM' in site_instance.info['EXTRA']:
                        selenium_tag = site_instance.info['SELENIUM_WAIT_TAG']

                    data = LogicFromSite.get_html(item['url'], cookie=cookie, selenium_tag=selenium_tag)
                    tree = html.fromstring(data)

                    # Step 2. 마그넷 목록 생성
                    item['magnet'] = LogicFromSite.__get_magnet_list(data, tree, site_instance)
                    
                    # Step 3. 다운로드 목록 생성                
                    item['download'] = LogicFromSite.__get_download_list(data, tree, site_instance, item)

                    # Stem 4. Torrent_info
                    item['torrent_info'] = LogicFromSite.__get_torrent_info(item['magnet'], scheduler_instance)

                    if 'SLEEP_5' in site_instance.info['EXTRA']: 
                        sleep(5)
                    if 'DELAY' in site_instance.info:
                        sleep(site_instance.info['DELAY'])
                except Exception as e: 
                    logger.error('Exception:%s', e)
                    logger.error(traceback.format_exc())
                    item['magnet'] = None


                count += 1
                if count >= max_count:
                    break

            return bbs_list
        except Exception as e: 
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            return None

    @staticmethod
    def __get_bbs_list(site_instance, board, max_page, max_id, xpath_dict, is_test=False):
        bbs_list = []
        index_step = xpath_dict['INDEX_STEP'] if 'INDEX_STEP' in xpath_dict else 1
        index_start = xpath_dict['INDEX_START'] if 'INDEX_START' in xpath_dict else 1
        stop_by_maxid = False
        if 'FORCE_FIRST_PAGE' in site_instance.info['EXTRA']:
            max_page = 1
        cookie = None
        if 'COOKIE' in site_instance.info:
            cookie = site_instance.info['COOKIE']

        for p in range(max_page):
            url = LogicFromSite.get_board_url(site_instance, board, str(p+1))
            list_tag = xpath_dict['XPATH'][:xpath_dict['XPATH'].find('[%s]')]
            #list_tag = '/html/body/main/div/div/div[3]/div/table/tbody'
            logger.debug('list_tag : %s', list_tag)

            logger.debug('Url : %s', url)
            if 'USE_SELENIUM' in site_instance.info['EXTRA']:
                from system import SystemLogicSelenium
                tmp = SystemLogicSelenium.get_pagesoruce_by_selenium(url, list_tag)
            else:
                tmp = LogicFromSite.get_html(url, cookie=cookie)
            #logger.debug(tmp)
            tree = html.fromstring(tmp)
            #tree = html.fromstring(LogicFromSite.get_html(url)))

            
            lists = tree.xpath(list_tag)

            logger.debug('Count : %s', len(lists))
            
            for i in range(index_start, len(lists)+1, index_step):
                try:
                    a_tag = tree.xpath(xpath_dict['XPATH'] % i)
                    a_tag_index = len(a_tag)-1
                    
                    if a_tag_index == -1:
                        logger.debug('a_tag_index : %s', a_tag_index)
                        continue
                    item = {}
                    #
                    if 'TITLE_XPATH' in xpath_dict:

                        #logger.debug(a_tag[a_tag_index].xpath(xpath_dict['TITLE_XPATH']))
                        if xpath_dict['TITLE_XPATH'].endswith('text()'):
                            logger.debug(a_tag[a_tag_index].xpath(xpath_dict['TITLE_XPATH']))

                            item['title'] = py_urllib.unquote(a_tag[a_tag_index].xpath(xpath_dict['TITLE_XPATH'])[-1]).strip()
                        else:
                            item['title'] = py_urllib.unquote(a_tag[a_tag_index].xpath(xpath_dict['TITLE_XPATH'])[0].text_content()).strip()
                    else:
                        item['title'] = py_urllib.unquote(a_tag[a_tag_index].text_content()).strip()
                    
                    if 'TITLE_SUB' in xpath_dict:
                        item['title'] = re.sub(xpath_dict['TITLE_SUB'][0], xpath_dict['TITLE_SUB'][1], item['title']).strip()

                    # 일반적이 제목 처리 후 정규식이 있으면 추출
                    if 'TITLE_REGEX' in xpath_dict:
                        match = re.compile(xpath_dict['TITLE_REGEX']).search(item['title'])
                        if match:
                            item['title'] = match.group('title')

                    item['url'] = a_tag[a_tag_index].attrib['href']
                    if 'DETAIL_URL_SUB' in site_instance.info:
                        #item['url'] = item['url'].replace(site_instance.info['DETAIL_URL_RULE'][0], site_instance.info['DETAIL_URL_RULE'][1].format(URL=site_instance.info['TORRENT_SITE_URL']))
                        item['url'] = re.sub(site_instance.info['DETAIL_URL_SUB'][0], site_instance.info['DETAIL_URL_SUB'][1].format(URL=site_instance.info['TORRENT_SITE_URL']), item['url'])


                    if not item['url'].startswith('http'):
                        form = '%s%s' if item['url'].startswith('/') else '%s/%s'
                        item['url'] = form % (site_instance.info['TORRENT_SITE_URL'], item['url'])
                    
                    item['id'] = ''
                    if 'ID_REGEX' in site_instance.info:
                        id_regexs = [site_instance.info['ID_REGEX']]
                        #id_regexs.insert(0, site_instance.info['ID_REGEX'])
                    else:
                        id_regexs = [r'wr_id\=(?P<id>\d+)', r'\/(?P<id>\d+)\.html', r'\/(?P<id>\d+)$']
                    for regex in id_regexs:
                        match = re.compile(regex).search(item['url'])
                        if match:
                            item['id'] = match.group('id')
                            break
                    if item['id'] == '':
                        for regex in id_regexs:
                            match = re.compile(regex).search(item['url'].split('?')[0])
                            if match:
                                item['id'] = match.group('id')
                                break
                    
                    logger.debug('ID : %s, TITLE : %s', item['id'], item['title'])
                    if item['id'].strip() == '':
                        continue
                    if is_test:
                        bbs_list.append(item)
                    else:
                        if 'USING_BOARD_CHAR_ID' in site_instance.info['EXTRA']:
                            # javdb
                            from .model import ModelBbs2
                            entity = ModelBbs2.get(site=site_instance.info['NAME'], board=board, board_char_id=item['id'])
                            if entity is None:
                                bbs_list.append(item)
                                logger.debug('> Append..')
                            else:
                                logger.debug('> exist..')
                        else:
                            # 2019-04-04 토렌트퐁
                            try:
                                if 'NO_BREAK_BY_MAX_ID' in site_instance.info['EXTRA']:
                                    if int(item['id']) <= max_id:
                                        continue
                                    else:
                                        bbs_list.append(item)
                                else:
                                    if int(item['id']) <= max_id:
                                        logger.debug('STOP by MAX_ID(%s)', max_id)
                                        stop_by_maxid = True
                                        break
                                    bbs_list.append(item)
                                    #logger.debug(item)
                            except Exception as e:
                                logger.error('Exception:%s', e)
                                logger.error(traceback.format_exc())            
                except Exception as e:
                    logger.error('Exception:%s', e)
                    logger.error(traceback.format_exc())
                    logger.error(site_instance.info)
            if stop_by_maxid:
                break
        logger.debug('Last count :%s', len(bbs_list))
        return bbs_list


    # Step2. 마그넷 목록을 생성한다.
    @staticmethod
    def __get_magnet_list(html, tree, site_instance):
        magnet_list = []
        try:
            if 'MAGNET_REGAX' not in site_instance.info:
                try:
                    link_element = tree.xpath("//a[starts-with(@href,'magnet')]")
                    if link_element:
                        for magnet in link_element:
                            # text가 None인걸로 판단하면 안된다.
                            # 텍스트가 child tag 안에 있을 수 있음.
                            #if magnet.text is None or not magnet.text.startswith('magnet'): 
                            #    break
                            if 'MAGNET_EXIST_ON_LIST' in site_instance.info['EXTRA']:
                                if magnet.text is None or not magnet.text.startswith('magnet'):
                                    break
                            tmp = (magnet.attrib['href']).lower()[:60]
                            if tmp not in magnet_list:
                                magnet_list.append(tmp)
                            #logger.debug('MARNET : %s', item['magnet'])
                    
                    #2020-09-17 javdb 동명 컨텐츠 너무 많이 뜸
                    if len(magnet_list) > 3:
                        magnet_list = magnet_list[:3]
                except Exception as e:
                    logger.debug('Exception:%s', e)
                    logger.debug(traceback.format_exc())
            #마그넷 regex
            #elif site['HOW'] == 'USING_MAGNET_REGAX':
            else:
                try:
                    match = re.compile(site_instance.info['MAGNET_REGAX'][0]).findall(html)
                    for m in match:
                        tmp = (site_instance.info['MAGNET_REGAX'][1] % m).lower()
                        if 'MAGNET_REGAX_REPLACE' in site_instance.info['EXTRA']:
                            tmp = re.sub('\'', '', tmp)
                            tmp = re.sub('\(', '', tmp)
                            tmp = re.sub('\)', '', tmp)
                            tmp = re.sub('buymagnet0', 'magnet:?xt=urn:btih:', tmp)
                        if tmp not in magnet_list:
                            magnet_list.append(tmp)
                    #logger.debug('MARNET : %s', magnet_list)
                except Exception as e:
                    logger.debug('Exception:%s', e)
                    logger.debug(traceback.format_exc())
            # 2020-12-23
            if 'MAGNET_ONLY_ONE_LAST' in site_instance.info['EXTRA']:
                magnet_list = [magnet_list[-1]]
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())
        return magnet_list


    # Step 3. 다운로드 목록 생성
    @staticmethod
    def __get_download_list(html, tree, site_instance, item):
        download_list = []
        try:
            if 'DOWNLOAD_REGEX' not in site_instance.info:
                return download_list
            #logger.debug(html)
            #tmp = html.find('a href="https://www.rgtorrent.me/bbs/download.php')
            #if tmp != -1:
            #    logger.debug(html[tmp-300:tmp+300])
            #logger.debug(site_instance.info['DOWNLOAD_REGEX'])
            tmp = re.compile(site_instance.info['DOWNLOAD_REGEX'], re.MULTILINE).finditer(html)
            for t in tmp:
                #logger.debug(t.group('url'))
                #logger.debug(t.group('filename'))
                if t.group('filename').strip() == '':
                    continue
                entity = {}
                entity['link'] = py_urllib.unquote(t.group('url').strip()).strip()
                entity['link'] = unescape(entity['link'])
                logger.debug(entity['link'])
                entity['filename'] = py_urllib.unquote(t.group('filename').strip())
                entity['filename'] = unescape(entity['filename'])
                if 'DOWNLOAD_URL_SUB' in site_instance.info:
                    logger.debug(entity['link'])
                    entity['link'] = re.sub(site_instance.info['DOWNLOAD_URL_SUB'][0], site_instance.info['DOWNLOAD_URL_SUB'][1].format(URL=site_instance.info['TORRENT_SITE_URL']), entity['link']).strip()
                if not entity['link'].startswith('http'):
                    form = '%s%s' if entity['link'].startswith('/') else '%s/%s'
                    entity['link'] = form % (site_instance.info['TORRENT_SITE_URL'], entity['link'])
                if 'FILENAME_SUB' in site_instance.info:
                    entity['filename'] = re.sub(site_instance.info['FILENAME_SUB'][0], site_instance.info['FILENAME_SUB'][1], entity['filename']).strip()
                exist = False
                for tt in download_list:
                    if tt['link'] == entity['link']:
                        exist = True
                        break
                if not exist:
                    if app.config['config']['is_server'] and len(item['magnet'])>0:# or True:
                        try:
                            ext = os.path.splitext(entity['filename'])[1].lower()
                            #item['magnet']
                            if ext in ['.smi', '.srt', '.ass']:
                            #if True:
                                import io
                                if 'USE_SELENIUM' in site_instance.info['EXTRA']:
                                    from system import SystemLogicSelenium
                                    driver = SystemLogicSelenium.get_driver()
                                    driver.get(entity['link'])
                                    import time
                                    time.sleep(10)
                                    files = SystemLogicSelenium.get_downloaded_files()
                                    logger.debug(files)
                                    # 파일확인
                                    filename_no_ext = os.path.splitext(entity['filename'].split('/')[-1])
                                    file_index = 0
                                    for idx, value in enumerate(files):
                                        if value.find(filename_no_ext[0]) != -1:
                                            file_index =  idx
                                            break
                                    logger.debug('fileindex : %s', file_index)
                                    content = SystemLogicSelenium.get_file_content(files[file_index])
                                    
                                    byteio = io.BytesIO()
                                    byteio.write(content)
                                else:
                                    data = LogicFromSite.get_html(entity['link'], referer=item['url'], stream=True)
                                    byteio = io.BytesIO()
                                    for chunk in data.iter_content(1024):
                                        byteio.write(chunk)
                                from tool_expand import ToolExpandDiscord
                                entity['direct_url'] = ToolExpandDiscord.discord_cdn(byteio=byteio, filename=entity['filename'], webhook_url=app.config['DEFINE']['RSS_SUBTITLE_UPLOAD_WEBHOOK'], content='%s\n<%s>' % (item['title'], item['url']))
                        except Exception as e:
                            logger.debug('Exception:%s', e)
                            logger.debug(traceback.format_exc())
                    download_list.append(entity)
            return download_list

        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())
        return download_list

    # Step 4. Torrent Info
    @staticmethod
    def __get_torrent_info(magnet_list, scheduler_instance):
        ret = None
        try:
            #if not ModelSetting.get_bool('use_torrent_info'):
            #    return ret
            # 스케쥴링
            if scheduler_instance is not None:
                if not scheduler_instance.use_torrent_info:
                    return ret
            else:
                #테스트
                if not ModelSetting.get_bool('use_torrent_info'):
                    return ret

            ret = []
            from torrent_info import Logic as TorrentInfoLogic
            for m in magnet_list:
                logger.debug('Get_torrent_info:%s', m)
                for i in range(1):
                    tmp = None
                    try:
                        tmp = TorrentInfoLogic.parse_magnet_uri(m, no_cache=True)
                    except:
                        logger.debug('Timeout..')
                    if tmp is not None:
                        break
                    
                if tmp is not None:
                    ret.append(tmp)
                    #ret[m] = tmp
        except Exception as e:
            logger.debug('Exception:%s', e)
            logger.debug(traceback.format_exc())
        return ret

    @staticmethod
    def get_data(url):
        import ssl
        data = None
        for i in range(3):
            try:
                request = py_urllib2.Request(url, headers=headers)
                logger.debug(url)
                data = py_urllib2.urlopen(request).read()
            except Exception as e:
                logger.debug('Exception:%s', e)
                logger.debug(traceback.format_exc())
                try:
                    data = py_urllib2.urlopen(request, headers=headers, context=ssl.SSLContext(ssl.PROTOCOL_TLSv1)).read()
                except:
                    try:
                        data = py_urllib2.urlopen(request, headers=headers, context=ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)).read()
                    except:
                        try:
                            data = py_urllib2.urlopen(request, headers=headers, context=ssl.SSLContext(ssl.PROTOCOL_TLSv1_3)).read()
                        except:
                            pass
            if data is not None:
                return data
            sleep(5)

    @staticmethod
    def set_proxy(scheduler_instance):
        try:
            LogicFromSite.session.keep_alive = False
            flag = False
            proxy_url = ModelSetting.get('proxy_url')

            if scheduler_instance:
                logger.debug('USE_PROXY : %s', scheduler_instance.use_proxy)
                if scheduler_instance.use_proxy:
                    flag = True
            else:
                flag = ModelSetting.get_bool('use_proxy')
            if flag:
                LogicFromSite.proxyes = { 
                "http"  : proxy_url, 
                "https" : proxy_url, 
                }
            else:
                LogicFromSite.proxyes = None
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
    
    @staticmethod
    def get_html(url, referer=None, stream=False, cookie=None, selenium_tag=None):
        try:
            logger.debug('get_html :%s', url)
            if selenium_tag:
                #if 'USE_SELENIUM' in site_instance.info['EXTRA']:
                from system import SystemLogicSelenium
                data = SystemLogicSelenium.get_pagesoruce_by_selenium(url, selenium_tag)

            else:
                headers['Referer'] = '' if referer is None else referer
                if cookie is not None:
                    headers['Cookie'] = cookie

                if LogicFromSite.proxyes:
                    page_content = LogicFromSite.session.get(url, headers=headers, proxies=LogicFromSite.proxyes, stream=stream, verify=False)
                else:
                    page_content = LogicFromSite.session.get(url, headers=headers, stream=stream, verify=False)
                if cookie is not None:
                    del headers['Cookie']
                if stream:
                    return page_content
                data = page_content.text
            #logger.debug(data)
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())
            logger.error('Known..')
            data = LogicFromSite.get_data(url)
        return data

    @staticmethod
    def get_board_url(site_instance, board, page):
        try:
            if board == "NONE":
                board = ""
            if 'BOARD_URL_RULE' in site_instance.info:
                if site_instance.info['BOARD_URL_RULE'].find('{BOARD_NAME_1}') != -1:
                    tmp = board.split(',')
                    url = site_instance.info['BOARD_URL_RULE'].format(URL=site_instance.info['TORRENT_SITE_URL'], BOARD_NAME_1=tmp[0], BOARD_NAME_2=tmp[1], PAGE=page)
                else:
                    url = site_instance.info['BOARD_URL_RULE'].format(URL=site_instance.info['TORRENT_SITE_URL'], BOARD_NAME=board, PAGE=page)
            else:
                url = '%s/bbs/board.php?bo_table=%s&page=%s' % (site_instance.info['TORRENT_SITE_URL'], board, page)
            return url
        except Exception as e:
            logger.error('Exception:%s', e)
            logger.error(traceback.format_exc())


