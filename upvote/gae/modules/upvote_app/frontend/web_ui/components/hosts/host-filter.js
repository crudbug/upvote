// Copyright 2017 Google Inc. All Rights Reserved.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS-IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

goog.provide('upvote.hosts.prettifyEnforcementLevel');
goog.provide('upvote.hosts.prettifyMode');

goog.require('upvote.hosts.ClientMode');
goog.require('upvote.hosts.PolicyLevel');


/**
 * Return a prettier representation of the host mode.
 * @param {?string} inputString
 * @return {?string}
 */
upvote.hosts.prettifyMode = function(inputString) {
  if (!angular.isString(inputString)) {
    return inputString;
  } else if (inputString == upvote.hosts.ClientMode.LOCKDOWN) {
    return 'Protected';
  } else if (inputString == upvote.hosts.ClientMode.MONITOR) {
    return 'Minimally Protected';
  } else {
    return 'Unknown';
  }
};


/**
 * Translate the Bit9 policy level to a host mode.
 * @param {?string} enforcementLevel
 * @return {?string}
 */
upvote.hosts.prettifyEnforcementLevel = (enforcementLevel) => {
  if (!angular.isString(enforcementLevel)) {
    return enforcementLevel;
  }
  switch (enforcementLevel) {
    case upvote.hosts.PolicyLevel.LOCKDOWN:
      return 'Protected';
    case upvote.hosts.PolicyLevel.BLOCK_AND_ASK:
      return 'Mostly Protected';
    case upvote.hosts.PolicyLevel.MONITOR:
      return 'Minimally Protected';
    case upvote.hosts.PolicyLevel.DISABLED:
      return 'Unprotected';
    default:
      return 'Unknown';
  }
};

