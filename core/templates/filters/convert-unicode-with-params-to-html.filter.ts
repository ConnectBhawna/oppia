// Copyright 2019 The Oppia Authors. All Rights Reserved.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS-IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

/**
 * @fileoverview Converts {{name}} substrings to
 * <oppia-parameter>name</oppia-parameter> tags and unescapes the
 * {, } and \ characters. This is done by reading the given string from
 * left to right: if we see a backslash, we use the following character;
 * if we see a '{{', this is the start of a parameter; if we see a '}}';
 * this is the end of a parameter.
 */

import { Injectable, Pipe, PipeTransform, SecurityContext } from '@angular/core';
import { DomSanitizer } from '@angular/platform-browser';

require('filters/convert-unicode-to-html.filter.ts');

@Injectable({
  providedIn: 'root'
})
 @Pipe({
   name: 'convertUnicodeWithParamsToHtml'
 })
export class ConvertUnicodeWithParamsToHtmlPipe implements PipeTransform {
  constructor(private domSanitizer: DomSanitizer) {}

  private _assert(text: string | boolean): void {
    if (!text) {
      throw new Error('Invalid unicode-string-with-parameters: ' + text);
    }
  }

  transform(text: string): string {
    // The parsing here needs to be done with more care because we are
    // replacing two-character strings. We can't naively break by {{ because
    // in strings like \{{{ the second and third characters will be taken as
    // the opening brackets, which is wrong. We can't unescape characters
    // because then the { characters that remain will be ambiguous (they may
    // either be the openings of parameters or literal '{' characters entered
    // by the user. So we build a standard left-to-right parser which examines
    // each character of the string in turn, and processes it accordingly.
    var textFragments = [];
    var currentFragment = '';
    var currentFragmentIsParam = false;
    for (var i = 0; i < text.length; i++) {
      if (text[i] === '\\') {
        this._assert(!currentFragmentIsParam && text.length > i + 1 && {
          '{': true,
          '}': true,
          '\\': true
        }[text[i + 1]]);
        currentFragment += text[i + 1];
        i++;
      } else if (text[i] === '{') {
        this._assert(
          text.length > i + 1 && !currentFragmentIsParam &&
           text[i + 1] === '{');
        textFragments.push({
          type: 'text',
          data: currentFragment
        });
        currentFragment = '';
        currentFragmentIsParam = true;
        i++;
      } else if (text[i] === '}') {
        this._assert(
          text.length > i + 1 && currentFragmentIsParam &&
           text[i + 1] === '}');
        textFragments.push({
          type: 'parameter',
          data: currentFragment
        });
        currentFragment = '';
        currentFragmentIsParam = false;
        i++;
      } else {
        currentFragment += text[i];
      }
    }

    this._assert(!currentFragmentIsParam);
    textFragments.push({
      type: 'text',
      data: currentFragment
    });

    var result = '';
    textFragments.forEach((fragment) => {
      result += (
         fragment.type === 'text' ?
         this.domSanitizer.sanitize(SecurityContext.HTML, fragment.data) :
         '<oppia-parameter>' + fragment.data +
         '</oppia-parameter>');
    });
    return result;
  }
}

angular.module('oppia').filter('convertUnicodeWithParamsToHtml', [
  '$filter', function($filter) {
    var assert = function(text) {
      if (!text) {
        throw new Error('Invalid unicode-string-with-parameters: ' + text);
      }
    };

    return function(text) {
      // The parsing here needs to be done with more care because we are
      // replacing two-character strings. We can't naively break by {{ because
      // in strings like \{{{ the second and third characters will be taken as
      // the opening brackets, which is wrong. We can't unescape characters
      // because then the { characters that remain will be ambiguous (they may
      // either be the openings of parameters or literal '{' characters entered
      // by the user. So we build a standard left-to-right parser which examines
      // each character of the string in turn, and processes it accordingly.
      var textFragments = [];
      var currentFragment = '';
      var currentFragmentIsParam = false;
      for (var i = 0; i < text.length; i++) {
        if (text[i] === '\\') {
          assert(!currentFragmentIsParam && text.length > i + 1 && {
            '{': true,
            '}': true,
            '\\': true
          }[text[i + 1]]);
          currentFragment += text[i + 1];
          i++;
        } else if (text[i] === '{') {
          assert(
            text.length > i + 1 && !currentFragmentIsParam &&
            text[i + 1] === '{');
          textFragments.push({
            type: 'text',
            data: currentFragment
          });
          currentFragment = '';
          currentFragmentIsParam = true;
          i++;
        } else if (text[i] === '}') {
          assert(
            text.length > i + 1 && currentFragmentIsParam &&
            text[i + 1] === '}');
          textFragments.push({
            type: 'parameter',
            data: currentFragment
          });
          currentFragment = '';
          currentFragmentIsParam = false;
          i++;
        } else {
          currentFragment += text[i];
        }
      }

      assert(!currentFragmentIsParam);
      textFragments.push({
        type: 'text',
        data: currentFragment
      });

      var result = '';
      textFragments.forEach(function(fragment) {
        result += (
          fragment.type === 'text' ?
          $filter('convertUnicodeToHtml')(fragment.data) :
          '<oppia-parameter>' + fragment.data +
          '</oppia-parameter>');
      });
      return result;
    };
  }]);
