// Copyright 2022 The Oppia Authors. All Rights Reserved.
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

import { LearnerGroupData } from './learner-group.model';

/**
 * @fileoverview Tests for learner group model.
 */

describe('Learner Group Object', () => {
  let sampleLearnerGroupData: LearnerGroupData;

  beforeEach(() => {
    let sampleLearnerGroupDataDict = {
      id: 'sampleId',
      title: 'sampleTitle',
      description: 'sampleDescription',
      facilitator_usernames: ['username1'],
      student_usernames: [],
      invited_student_usernames: ['sampleUsername'],
      subtopic_page_ids: ['sampleSubtopicPageId'],
      story_ids: []
    };
    sampleLearnerGroupData = LearnerGroupData.createFromBackendDict(
      sampleLearnerGroupDataDict);
  });

  it('should not find issues with a valid learner group', () => {
    expect(sampleLearnerGroupData.validate(false)).toEqual([]);
  });

  it('should raise correct validation issues', () => {
    sampleLearnerGroupData.title = '';
    sampleLearnerGroupData.description = '';
    sampleLearnerGroupData.removeFacilitator('username1');
    sampleLearnerGroupData.addStudent('sampleUsername');

    expect(sampleLearnerGroupData.validate(false)).toEqual([
      'Learner Group title should not be empty.',
      'Learner Group description should not be empty.',
      'Learner Group should have at least one facilitator.',
      'Students can not be invited to join the same group again.'
    ]);
  });

  it('should not find issues with a valid creatable learner group', () => {
    expect(sampleLearnerGroupData.validate(true)).toEqual([]);
  });

  it('should raise correct validation issues for pre creation' +
    ' validation', () => {
    sampleLearnerGroupData.title = '';
    sampleLearnerGroupData.description = '';
    sampleLearnerGroupData.removeFacilitator('username1');
    sampleLearnerGroupData.addStudent('sampleUsername2');
    sampleLearnerGroupData.removeSubtopicPageId('sampleSubtopicPageId');

    expect(sampleLearnerGroupData.validate(true)).toEqual([
      'Learner Group title should not be empty.',
      'Learner Group description should not be empty.',
      'Learner Group should have at least one facilitator.',
      'Learner Group should have at least one syllabus item.',
      'Learner Group cannot have any students while creation.'
    ]);
  });

  it('should correctly update properties', () => {
    sampleLearnerGroupData.title = 'title1';
    sampleLearnerGroupData.description = 'description1';
    sampleLearnerGroupData.addFacilitator('username2');
    sampleLearnerGroupData.removeFacilitator('username1');
    sampleLearnerGroupData.addStudent('username2');
    sampleLearnerGroupData.addStudent('username3');
    sampleLearnerGroupData.removeStudent('username2');
    sampleLearnerGroupData.inviteStudent('username4');
    sampleLearnerGroupData.revokeInvitation('sampleUsername');
    sampleLearnerGroupData.addSubtopicPageId('subtopicPageId1');
    sampleLearnerGroupData.removeSubtopicPageId('sampleSubtopicPageId');
    sampleLearnerGroupData.addStoryId('storyId1');
    sampleLearnerGroupData.addStoryId('storyId2');
    sampleLearnerGroupData.removeStoryId('storyId1');

    expect(sampleLearnerGroupData.title).toEqual('title1');
    expect(sampleLearnerGroupData.description).toEqual('description1');
    expect(sampleLearnerGroupData.facilitatorUsernames).toEqual(['username2']);
    expect(sampleLearnerGroupData.studentUsernames).toEqual(['username3']);
    expect(sampleLearnerGroupData.invitedStudentUsernames).toEqual(
      ['username4']);
    expect(sampleLearnerGroupData.subtopicPageIds).toEqual(
      ['subtopicPageId1']);
    expect(sampleLearnerGroupData.storyIds).toEqual(['storyId2']);
  });
});
