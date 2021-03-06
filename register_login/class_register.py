#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import random
import string
import time
from .forms import RegisterForm, SendVerifyEmailForm
from package.response_data import get_res_json
from libs.md5_lingling import Md5Tool
from mysql_lingling import MySQLTool
from config.mysql_options import mysql_config
from package.get_time import get_date_time
from package.mail.client import MailManager
from package.href_str import get_href
from django.conf import settings

# 账号激活邮件发送间隔
DURATION_SEC_SEND_VERIFY_TIME = 60


# 返回验证链接
def _get_verify_href(email, vcode):
    # HOST = 'http://127.0.0.1:8000'
    # search_s = get_search_str()
    # href = '%s/verify_email?%s' % (HOST, search_s)
    href = get_href('verify_email', {
        'email': email,
        'vcode': vcode
    })
    return href


class RegisterManager(object):
    def __init__(self, request):
        self.request = request

    # 获取请求的数据，并校验（用于标准注册逻辑）
    def load_data(self):
        data = None
        # 取出数据
        if len(self.request.body) is 0:
            return {
                'is_pass': False,
                'res': get_res_json(code=0, msg='需要【邮箱】、【密码】')
            }
        try:
            data = json.loads(self.request.body)
        except BaseException as e:
            return {
                'is_pass': False,
                'res': get_res_json(code=0, msg='数据非法')
            }

        return {
            'is_pass': True,
            'res': data
        }

    # 执行注册逻辑
    def register(self, data):
        # 验证
        verify_result = self._verify(data)
        # 验证失败，返回报错信息
        if verify_result['is_pass'] is False:
            return verify_result['res']

        save_result = self._save(data)
        return save_result

    # 发送验证邮件（这里可能需要再次发送验证邮件）
    def _send_verify_email(self, email, vcode):
        mm = MailManager()
        href = _get_verify_href(email, vcode)
        content = '请点击链接\n%s' % href
        # 这里是测试读取 html 内容（即发送超文本样式），也可以只发纯文本
        # with open('./content.html', 'r', encoding='utf-8') as f:
        #     content = ''.join(f.readlines()).replace(' ', '').replace('\n', '')
        mail_data = {
            'receiver': [email],
            'title': '表白墙账号注册激活邮件',
            'content': content,
            'account': '使用邮件服务的账号（指服务，而不是邮箱的账号）',
            'pw': '使用邮件服务的密码（指服务，而不是邮箱的密码）'
        }
        res2 = mm.send_mail(mail_data)
        # print(res2)
        return res2

    # 校验输入内容
    def _verify(self, data):
        uf = RegisterForm(data)
        # 验证不通过，返回错误信息
        if not uf.is_valid():
            msg = uf.get_form_error_msg()
            return {
                'is_pass': False,
                'res': get_res_json(code=0, msg=msg)
            }
        return {
            'is_pass': True
        }

    # 保存
    def _save(self, data):
        # 拿取数据
        email = data.get('email')
        password = data.get('password')
        phone = data.get('phone', None)

        # 密码加密
        tool = Md5Tool()
        md5pw = tool.get_md5(password)
        print(email, md5pw, phone)

        result = self._save_into_mysql(email, md5pw, phone)
        # 如果返回结果是 False，说明执行失败
        return result

    # 在数据库里进行保存
    def _save_into_mysql(self, email, md5pw, phone):
        vcode = None
        # 连接数据库
        with MySQLTool(host=mysql_config['host'],
                       user=mysql_config['user'],
                       password=mysql_config['pw'],
                       port=mysql_config['port'],
                       database=mysql_config['database']) as mtool:
            # 查看有没有同名的用户
            result = mtool.run_sql([
                ['select (email) from user_auth where email = %s', [email]]
            ])
            # 打印结果e
            print(result)
            # 判定密码是否相等
            if len(result) > 0:
                return get_res_json(code=0, msg="该邮箱已注册，请更换邮箱")

            # 获取当前时间
            nowtime = get_date_time()

            # 插入
            row_id = mtool.insert_row(
                'INSERT user_auth'
                '(id, email, pw, phone, permission, status, create_time, lastlogin_time) VALUES'
                '(%s, %s,   %s,  %s,    0,          0,      %s,          %s)',
                [
                    None,
                    email,
                    md5pw,
                    phone,
                    nowtime,
                    nowtime
                ]
            )

            if row_id is False:
                mtool.uncommit()
                return get_res_json(code=0, msg='注册失败')

            # 插入数据到 user_info 表里
            insert_ui_result = self.insert_userinfo(mtool, email)
            if insert_ui_result['is_pass'] is False:
                mtool.uncommit()
                return get_res_json(code=0, msg='注册失败')

            vcode = self._get_verify_code()
            self._insert_info_into_verify(mtool, email, vcode)

        # 允许发送邮件
        if settings.ALLOWE_SEND_EMAIL is True:
            # 发送激活邮件给用户
            send_result = self._send_verify_email(email, vcode)
            # 发送失败——》返回错误信息
            if send_result.code is not 200:
                return get_res_json(code=200, data={
                    'msg': send_result.msg
                })

            # 此时跳转到邮件发送提示页面，提示用户点击邮箱里的链接进行验证
            return get_res_json(code=200, data={
                'msg': '用户注册成功，已发送激活邮件，请访问邮箱打开激活邮件以激活账号'
            })
        else:
            href = _get_verify_href(email, vcode)
            content = '请访问链接激活账号：\n%s' % href
            # 此时跳转到邮件发送提示页面，提示用户点击邮箱里的链接进行验证
            return get_res_json(code=200, data={
                'msg': content,
                'href': href
            })

    # 插入一条邮箱验证信息
    def _insert_info_into_verify(self, mtool, email, vcode):
        # 1、先检查该邮箱是否已有一条验证数据，有则使之失效
        # 2、插入一条该邮箱的验证信息
        # 1、使之失效
        u_result = mtool.update_row(
            'UPDATE verify_email SET is_invalid=1 WHERE email=%s',
            [
                email
            ]
        )
        # 获取当前时间
        nowtime = get_date_time()
        # 2、插入一条验证信息
        i_result = mtool.insert_row(
            'INSERT verify_email '
            '(email, verify_key, ctime) VALUES'
            '(%s,    %s,         %s)',
            [
                email,
                vcode,
                nowtime
            ]
        )

    # 生成一个验证码
    def _get_verify_code(self):
        length = 30
        vcode = ''.join(random.SystemRandom().choice(string.ascii_uppercase + string.digits) for _ in range(length))
        return vcode

    # 在 user_info 表里插入数据
    def insert_userinfo(self, mtool, email):
        insert_result = mtool.insert_row(
            'INSERT user_info'
            '(id)'
            'SELECT id FROM user_auth WHERE email=%s',
            [
                email
            ]
        )
        if insert_result is not False and insert_result > 0:
            return {
                'is_pass': True
            }
        else:
            return {
                'is_pass': False
            }


class SendVerifyEmailAgain(object):
    def __init__(self, request):
        self.request = request

    # 获取请求的数据，并校验（用于再次发送验证邮件）
    def load_data(self):
        data = None
        # 取出数据
        if len(self.request.body) is 0:
            return {
                'is_pass': False,
                'res': get_res_json(code=0, msg='需要【邮箱】')
            }
        try:
            data = json.loads(self.request.body)
        except BaseException as e:
            return {
                'is_pass': False,
                'res': get_res_json(code=0, msg='数据非法')
            }

        return {
            'is_pass': True,
            'res': data
        }

    # 再次发送验证邮件
    def send_verify_email_again(self, data):
        # 流程描述：
        # 1、拿到该email；（没拿到：报错返回）
        # 2、判断该email是否注册；（未注册：报错返回）
        # 3、判断该email是否已发送验证邮件；
        # 3.1、未发送：进入5
        # 3.2、已发送：进入4；
        # 4、判断上一次发送邮件的时间距离当前时间的间隔，是否小于间隔时间：
        # 4.1、小于间隔时间，提示等一段时间再申请重发验证邮件（返回）；
        # 4.2、大于等于间隔时间，进入5；
        # 5、发送验证右键，直接发送验证邮件（返回，告诉用户已发送）

        # 【1】步
        verify_result = self._verify_data(data)
        # 验证失败，返回报错信息
        if verify_result['is_pass'] is False:
            return verify_result['res']

        with MySQLTool(host=mysql_config['host'],
                       user=mysql_config['user'],
                       password=mysql_config['pw'],
                       port=mysql_config['port'],
                       database=mysql_config['database']) as mtool:
            email = data['email']
            # 【2】【3】【4】
            is_can_result = self._is_can_send_eamil(mtool, email)
            if is_can_result['is_can'] is False:
                return is_can_result['res']

            # 【5】发送邮件
            # 生成验证码，
            vcode = self._get_verify_code()
            # 插入一条验证数据（并使之前失效），
            self._insert_info_into_verify(mtool, email, vcode)

            # 调用RPC服务，发送激活邮件给用户
            send_result = self._send_verify_email(email, vcode)

            # 发送失败——》返回错误信息
            if send_result.code is not 200:
                return get_res_json(code=200, data={
                    'msg': send_result.msg
                })

            # 此时跳转到邮件发送提示页面，提示用户点击邮箱里的链接进行验证
            return get_res_json(code=200, data={
                'msg': '已再次发送激活邮件，请访问邮箱打开激活邮件以激活账号'
            })

    # 校验输入内容（再次发送邮件时调用）
    def _verify_data(self, data):
        uf = SendVerifyEmailForm(data)
        # 验证不通过，返回错误信息
        if not uf.is_valid():
            msg = uf.get_form_error_msg()
            return {
                'is_pass': False,
                'res': get_res_json(code=0, msg=msg)
            }
        return {
            'is_pass': True
        }

    # 是否能发送验证邮件
    def _is_can_send_eamil(self, mtool, email):
        # 2、判断该email是否注册；（未注册：报错返回）
        # 3、判断该email是否已发送验证邮件；
        # 3.1、未发送：发送验证邮件（返回，告诉用户已发送）
        # 3.2、已发送：进入4；
        # 4、判断上一次发送邮件的时间距离当前时间的间隔，是否小于间隔时间：
        # 4.1、小于间隔时间，提示等一段时间再申请重发验证邮件（返回）；
        # 4.2、大于等于间隔时间，直接发送验证邮件（返回，告诉用户已发送）；
        select_ui_result = mtool.run_sql([
            [
                'SELECT count(*) FROM user_auth WHERE email = %s',
                [
                    email
                ]
            ]
        ])
        # 2、未注册：报错返回
        if select_ui_result is False or len(select_ui_result) <= 0 or select_ui_result[0][0] <= 0:
            return {
                'is_can': False,
                'res': get_res_json(code=0, msg='该邮箱未注册，请检查自己输入的邮箱地址是否正确，或联系管理员')
            }

        # 3、判断该email是否已发送验证邮件；
        select_ve_result = mtool.run_sql([
            [
                'SELECT ctime FROM verify_email WHERE email = %s and is_invalid=0',
                [
                    email
                ]
            ]
        ])
        l = len(select_ve_result)
        # 先判断有没有发送过
        if l is 0:
            # 3.1、没发送过
            return {
                'is_can': True
            }
        else:
            # 3.2、发送过，则判断最后一次发送的时间和当前时间
            last_send_time = select_ve_result[l - 1][0]
            last_sec = int(time.mktime(last_send_time.timetuple()))
            now_sec = int(time.time())
            sec_dur = now_sec - last_sec
            # 4、判断上一次发送邮件的时间距离当前时间的间隔，是否小于间隔时间：
            # 4.1、小于间隔时间，提示等一段时间再申请重发验证邮件（返回）；
            if sec_dur < DURATION_SEC_SEND_VERIFY_TIME:
                return {
                    'is_can': False,
                    'res': get_res_json(code=0, msg='你还需要等待 %s 秒 才能发送验证邮件' % sec_dur, data={
                        'seconds': sec_dur
                    })
                }
            else:
                # 4.2、可以发
                return {
                    'is_can': True
                }

    # 生成一个验证码
    def _get_verify_code(self):
        length = 30
        vcode = ''.join(random.SystemRandom().choice(string.ascii_uppercase + string.digits) for _ in range(length))
        return vcode

    # 插入一条邮箱验证信息
    def _insert_info_into_verify(self, mtool, email, vcode):
        # 1、先检查该邮箱是否已有一条验证数据，有则使之失效
        # 2、插入一条该邮箱的验证信息
        # 1、使之失效
        u_result = mtool.update_row(
            'UPDATE verify_email SET is_invalid=1 WHERE email=%s',
            [
                email
            ]
        )
        # 获取当前时间
        nowtime = get_date_time()
        # 2、插入一条验证信息
        i_result = mtool.insert_row(
            'INSERT verify_email '
            '(email, verify_key, ctime) VALUES'
            '(%s,    %s,         %s)',
            [
                email,
                vcode,
                nowtime
            ]
        )

    # 发送验证邮件（这里可能需要再次发送验证邮件）
    def _send_verify_email(self, email, vcode):
        mm = MailManager()
        href = _get_verify_href(email, vcode)
        content = '请点击链接 %s' % href
        # 这里是测试读取 html 内容（即发送超文本样式），也可以只发纯文本
        # with open('./content.html', 'r', encoding='utf-8') as f:
        #     content = ''.join(f.readlines()).replace(' ', '').replace('\n', '')
        mail_data = {
            'receiver': [email],
            'title': '表白墙账号注册激活邮件',
            'content': content,
            'account': '使用邮件服务的账号（指服务，而不是邮箱的账号）',
            'pw': '使用邮件服务的密码（指服务，而不是邮箱的密码）'
        }
        res2 = mm.send_mail(mail_data)
        # print(res2)
        return res2
