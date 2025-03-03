# coding: utf-8
#
# Copyright 2018 The Oppia Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS-IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.]

"""Commands for operations on topics, and related models."""

from __future__ import annotations

import collections
import logging

from core import feconf
from core import utils
from core.constants import constants
from core.domain import caching_services
from core.domain import feedback_services
from core.domain import fs_services
from core.domain import opportunity_services
from core.domain import rights_domain
from core.domain import role_services
from core.domain import state_domain
from core.domain import story_fetchers
from core.domain import story_services
from core.domain import subtopic_page_domain
from core.domain import subtopic_page_services
from core.domain import suggestion_services
from core.domain import topic_domain
from core.domain import topic_fetchers
from core.domain import user_services
from core.platform import models

from typing import Optional

(topic_models,) = models.Registry.import_models([models.NAMES.topic])
datastore_services = models.Registry.import_datastore_services()


def _create_topic(committer_id, topic, commit_message, commit_cmds):
    """Creates a new topic, and ensures that rights for a new topic
    are saved first.

    Args:
        committer_id: str. ID of the committer.
        topic: Topic. Topic domain object.
        commit_message: str. A description of changes made to the topic.
        commit_cmds: list(TopicChange). A list of TopicChange objects that
            represent change commands made to the given topic.
    """
    topic.validate()
    if does_topic_with_name_exist(topic.name):
        raise utils.ValidationError(
            'Topic with name \'%s\' already exists' % topic.name)
    if does_topic_with_url_fragment_exist(topic.url_fragment):
        raise utils.ValidationError(
            'Topic with URL Fragment \'%s\' already exists'
            % topic.url_fragment)
    create_new_topic_rights(topic.id, committer_id)
    model = topic_models.TopicModel(
        id=topic.id,
        name=topic.name,
        abbreviated_name=topic.abbreviated_name,
        url_fragment=topic.url_fragment,
        thumbnail_bg_color=topic.thumbnail_bg_color,
        thumbnail_filename=topic.thumbnail_filename,
        thumbnail_size_in_bytes=topic.thumbnail_size_in_bytes,
        canonical_name=topic.canonical_name,
        description=topic.description,
        language_code=topic.language_code,
        canonical_story_references=[
            reference.to_dict()
            for reference in topic.canonical_story_references],
        additional_story_references=[
            reference.to_dict()
            for reference in topic.additional_story_references],
        uncategorized_skill_ids=topic.uncategorized_skill_ids,
        subtopic_schema_version=topic.subtopic_schema_version,
        story_reference_schema_version=topic.story_reference_schema_version,
        next_subtopic_id=topic.next_subtopic_id,
        subtopics=[subtopic.to_dict() for subtopic in topic.subtopics],
        meta_tag_content=topic.meta_tag_content,
        practice_tab_is_displayed=topic.practice_tab_is_displayed,
        page_title_fragment_for_web=topic.page_title_fragment_for_web,
        skill_ids_for_diagnostic_test=topic.skill_ids_for_diagnostic_test
    )
    commit_cmd_dicts = [commit_cmd.to_dict() for commit_cmd in commit_cmds]
    model.commit(committer_id, commit_message, commit_cmd_dicts)
    topic.version += 1
    generate_topic_summary(topic.id)


def does_topic_with_name_exist(topic_name):
    """Checks if the topic with provided name exists.

    Args:
        topic_name: str. The topic name.

    Returns:
        bool. Whether the the topic name exists.

    Raises:
        Exception. Topic name is not a string.
    """
    if not isinstance(topic_name, str):
        raise utils.ValidationError('Name should be a string.')
    existing_topic = topic_fetchers.get_topic_by_name(topic_name)
    return existing_topic is not None


def does_topic_with_url_fragment_exist(url_fragment):
    """Checks if topic with provided url fragment exists.

    Args:
        url_fragment: str. The url fragment for the topic.

    Returns:
        bool. Whether the the url fragment for the topic exists.

    Raises:
        Exception. Topic URL fragment is not a string.
    """
    if not isinstance(url_fragment, str):
        raise utils.ValidationError('Topic URL fragment should be a string.')
    existing_topic = (
        topic_fetchers.get_topic_by_url_fragment(url_fragment))
    return existing_topic is not None


def save_new_topic(committer_id, topic):
    """Saves a new topic.

    Args:
        committer_id: str. ID of the committer.
        topic: Topic. Topic to be saved.
    """
    commit_message = (
        'New topic created with name \'%s\'.' % topic.name)
    _create_topic(
        committer_id, topic, commit_message, [topic_domain.TopicChange({
            'cmd': topic_domain.CMD_CREATE_NEW,
            'name': topic.name
        })])


def apply_change_list(topic_id, change_list):
    """Applies a changelist to a topic and returns the result. The incoming
    changelist should not have simultaneuous creations and deletion of
    subtopics.

    Args:
        topic_id: str. ID of the given topic.
        change_list: list(TopicChange). A change list to be applied to the given
            topic.

    Raises:
        Exception. The incoming changelist had simultaneuous creation and
            deletion of subtopics.

    Returns:
        tuple(Topic, dict, list(int), list(int), list(SubtopicPageChange)). The
        modified topic object, the modified subtopic pages dict keyed
        by subtopic page id containing the updated domain objects of
        each subtopic page, a list of ids of the deleted subtopics,
        a list of ids of the newly created subtopics and a list of changes
        applied to modified subtopic pages.
    """
    topic = topic_fetchers.get_topic_by_id(topic_id)
    newly_created_subtopic_ids = []
    existing_subtopic_page_ids_to_be_modified = []
    deleted_subtopic_ids = []
    modified_subtopic_pages_list = []
    modified_subtopic_pages = {}
    modified_subtopic_change_cmds = collections.defaultdict(list)

    for change in change_list:
        if (change.cmd ==
                subtopic_page_domain.CMD_UPDATE_SUBTOPIC_PAGE_PROPERTY):
            if change.subtopic_id < topic.next_subtopic_id:
                existing_subtopic_page_ids_to_be_modified.append(
                    change.subtopic_id)
                subtopic_page_id = (
                    subtopic_page_domain.SubtopicPage.get_subtopic_page_id(
                        topic_id, change.subtopic_id))
                modified_subtopic_change_cmds[subtopic_page_id].append(
                    change)
    modified_subtopic_pages_list = (
        subtopic_page_services.get_subtopic_pages_with_ids(
            topic_id, existing_subtopic_page_ids_to_be_modified))
    for subtopic_page in modified_subtopic_pages_list:
        modified_subtopic_pages[subtopic_page.id] = subtopic_page

    try:
        for change in change_list:
            if change.cmd == topic_domain.CMD_ADD_SUBTOPIC:
                topic.add_subtopic(
                    change.subtopic_id,
                    change.title,
                    change.url_fragment
                )
                subtopic_page_id = (
                    subtopic_page_domain.SubtopicPage.get_subtopic_page_id(
                        topic_id, change.subtopic_id))
                modified_subtopic_pages[subtopic_page_id] = (
                    subtopic_page_domain.SubtopicPage.create_default_subtopic_page( # pylint: disable=line-too-long
                        change.subtopic_id, topic_id)
                )
                modified_subtopic_change_cmds[subtopic_page_id].append(
                    subtopic_page_domain.SubtopicPageChange({
                        'cmd': 'create_new',
                        'topic_id': topic_id,
                        'subtopic_id': change.subtopic_id
                    }))
                newly_created_subtopic_ids.append(change.subtopic_id)
            elif change.cmd == topic_domain.CMD_DELETE_SUBTOPIC:
                topic.delete_subtopic(change.subtopic_id)
                if change.subtopic_id in newly_created_subtopic_ids:
                    raise Exception(
                        'The incoming changelist had simultaneous'
                        ' creation and deletion of subtopics.')
                deleted_subtopic_ids.append(change.subtopic_id)
            elif change.cmd == topic_domain.CMD_ADD_CANONICAL_STORY:
                topic.add_canonical_story(change.story_id)
            elif change.cmd == topic_domain.CMD_DELETE_CANONICAL_STORY:
                topic.delete_canonical_story(change.story_id)
            elif change.cmd == topic_domain.CMD_REARRANGE_CANONICAL_STORY:
                topic.rearrange_canonical_story(
                    change.from_index, change.to_index)
            elif change.cmd == topic_domain.CMD_ADD_ADDITIONAL_STORY:
                topic.add_additional_story(change.story_id)
            elif change.cmd == topic_domain.CMD_DELETE_ADDITIONAL_STORY:
                topic.delete_additional_story(change.story_id)
            elif change.cmd == topic_domain.CMD_ADD_UNCATEGORIZED_SKILL_ID:
                topic.add_uncategorized_skill_id(
                    change.new_uncategorized_skill_id)
            elif change.cmd == topic_domain.CMD_REMOVE_UNCATEGORIZED_SKILL_ID:
                topic.remove_uncategorized_skill_id(
                    change.uncategorized_skill_id)
            elif change.cmd == topic_domain.CMD_MOVE_SKILL_ID_TO_SUBTOPIC:
                topic.move_skill_id_to_subtopic(
                    change.old_subtopic_id, change.new_subtopic_id,
                    change.skill_id)
            elif change.cmd == topic_domain.CMD_REARRANGE_SKILL_IN_SUBTOPIC:
                topic.rearrange_skill_in_subtopic(
                    change.subtopic_id, change.from_index, change.to_index)
            elif change.cmd == topic_domain.CMD_REARRANGE_SUBTOPIC:
                topic.rearrange_subtopic(change.from_index, change.to_index)
            elif change.cmd == topic_domain.CMD_REMOVE_SKILL_ID_FROM_SUBTOPIC:
                topic.remove_skill_id_from_subtopic(
                    change.subtopic_id, change.skill_id)
            elif change.cmd == topic_domain.CMD_UPDATE_TOPIC_PROPERTY:
                if (change.property_name ==
                        topic_domain.TOPIC_PROPERTY_NAME):
                    topic.update_name(change.new_value)
                elif (change.property_name ==
                      topic_domain.TOPIC_PROPERTY_ABBREVIATED_NAME):
                    topic.update_abbreviated_name(change.new_value)
                elif (change.property_name ==
                      topic_domain.TOPIC_PROPERTY_URL_FRAGMENT):
                    topic.update_url_fragment(change.new_value)
                elif (change.property_name ==
                      topic_domain.TOPIC_PROPERTY_DESCRIPTION):
                    topic.update_description(change.new_value)
                elif (change.property_name ==
                      topic_domain.TOPIC_PROPERTY_LANGUAGE_CODE):
                    topic.update_language_code(change.new_value)
                elif (change.property_name ==
                      topic_domain.TOPIC_PROPERTY_THUMBNAIL_FILENAME):
                    update_thumbnail_filename(topic, change.new_value)
                elif (change.property_name ==
                      topic_domain.TOPIC_PROPERTY_THUMBNAIL_BG_COLOR):
                    topic.update_thumbnail_bg_color(change.new_value)
                elif (change.property_name ==
                      topic_domain.TOPIC_PROPERTY_META_TAG_CONTENT):
                    topic.update_meta_tag_content(change.new_value)
                elif (change.property_name ==
                      topic_domain.TOPIC_PROPERTY_PRACTICE_TAB_IS_DISPLAYED):
                    topic.update_practice_tab_is_displayed(change.new_value)
                elif (change.property_name ==
                      topic_domain.TOPIC_PROPERTY_PAGE_TITLE_FRAGMENT_FOR_WEB):
                    topic.update_page_title_fragment_for_web(change.new_value)
                elif (change.property_name ==
                      topic_domain
                      .TOPIC_PROPERTY_SKILL_IDS_FOR_DIAGNOSTIC_TEST):
                    topic.update_skill_ids_for_diagnostic_test(change.new_value)
            elif (change.cmd ==
                  subtopic_page_domain.CMD_UPDATE_SUBTOPIC_PAGE_PROPERTY):
                subtopic_page_id = (
                    subtopic_page_domain.SubtopicPage.get_subtopic_page_id(
                        topic_id, change.subtopic_id))
                if ((modified_subtopic_pages[subtopic_page_id] is None) or
                        (change.subtopic_id in deleted_subtopic_ids)):
                    raise Exception(
                        'The subtopic with id %s doesn\'t exist' % (
                            change.subtopic_id))

                if (change.property_name ==
                        subtopic_page_domain.
                        SUBTOPIC_PAGE_PROPERTY_PAGE_CONTENTS_HTML):
                    page_contents = state_domain.SubtitledHtml.from_dict(
                        change.new_value)
                    page_contents.validate()
                    modified_subtopic_pages[
                        subtopic_page_id].update_page_contents_html(
                            page_contents)

                elif (change.property_name ==
                      subtopic_page_domain.
                      SUBTOPIC_PAGE_PROPERTY_PAGE_CONTENTS_AUDIO):
                    modified_subtopic_pages[
                        subtopic_page_id].update_page_contents_audio(
                            state_domain.RecordedVoiceovers.from_dict(
                                change.new_value))
            elif change.cmd == topic_domain.CMD_UPDATE_SUBTOPIC_PROPERTY:
                if (change.property_name ==
                        topic_domain.SUBTOPIC_PROPERTY_TITLE):
                    topic.update_subtopic_title(
                        change.subtopic_id, change.new_value)
                if (change.property_name ==
                        topic_domain.SUBTOPIC_PROPERTY_THUMBNAIL_FILENAME):
                    update_subtopic_thumbnail_filename(
                        topic, change.subtopic_id, change.new_value)
                if (change.property_name ==
                        topic_domain.SUBTOPIC_PROPERTY_THUMBNAIL_BG_COLOR):
                    topic.update_subtopic_thumbnail_bg_color(
                        change.subtopic_id, change.new_value)
                if (change.property_name ==
                        topic_domain.SUBTOPIC_PROPERTY_URL_FRAGMENT):
                    topic.update_subtopic_url_fragment(
                        change.subtopic_id, change.new_value)

            elif (
                    change.cmd ==
                    topic_domain.CMD_MIGRATE_SUBTOPIC_SCHEMA_TO_LATEST_VERSION):
                # Loading the topic model from the datastore into a
                # Topic domain object automatically converts it to use the
                # latest schema version. As a result, simply resaving the
                # topic is sufficient to apply the schema migration.
                continue
        return (
            topic, modified_subtopic_pages, deleted_subtopic_ids,
            newly_created_subtopic_ids, modified_subtopic_change_cmds)

    except Exception as e:
        logging.error(
            '%s %s %s %s' % (
                e.__class__.__name__, e, topic_id, change_list)
        )
        raise e


def _save_topic(committer_id, topic, commit_message, change_list):
    """Validates a topic and commits it to persistent storage. If
    successful, increments the version number of the incoming topic domain
    object by 1.

    Args:
        committer_id: str. ID of the given committer.
        topic: Topic. The topic domain object to be saved.
        commit_message: str. The commit message.
        change_list: list(TopicChange). List of changes applied to a topic.

    Raises:
        Exception. Received invalid change list.
        Exception. The topic model and the incoming topic domain
            object have different version numbers.
    """
    if not change_list:
        raise Exception(
            'Unexpected error: received an invalid change list when trying to '
            'save topic %s: %s' % (topic.id, change_list))
    topic_rights = topic_fetchers.get_topic_rights(topic.id, strict=False)
    topic.validate(strict=topic_rights.topic_is_published)

    topic_model = topic_models.TopicModel.get(topic.id, strict=False)

    # Topic model cannot be None as topic is passed as parameter here and that
    # is only possible if a topic model with that topic id exists. Also this is
    # a private function and so it cannot be called independently with any
    # topic object.
    if topic.version > topic_model.version:
        raise Exception(
            'Unexpected error: trying to update version %s of topic '
            'from version %s. Please reload the page and try again.'
            % (topic_model.version, topic.version))
    if topic.version < topic_model.version:
        raise Exception(
            'Trying to update version %s of topic from version %s, '
            'which is too old. Please reload the page and try again.'
            % (topic_model.version, topic.version))

    topic_model.description = topic.description
    topic_model.name = topic.name
    topic_model.canonical_name = topic.canonical_name
    topic_model.abbreviated_name = topic.abbreviated_name
    topic_model.url_fragment = topic.url_fragment
    topic_model.thumbnail_bg_color = topic.thumbnail_bg_color
    topic_model.thumbnail_filename = topic.thumbnail_filename
    topic_model.thumbnail_size_in_bytes = topic.thumbnail_size_in_bytes
    topic_model.canonical_story_references = [
        reference.to_dict() for reference in topic.canonical_story_references
    ]
    topic_model.additional_story_references = [
        reference.to_dict() for reference in topic.additional_story_references
    ]
    topic_model.uncategorized_skill_ids = topic.uncategorized_skill_ids
    topic_model.subtopics = [subtopic.to_dict() for subtopic in topic.subtopics]
    topic_model.subtopic_schema_version = topic.subtopic_schema_version
    topic_model.story_reference_schema_version = (
        topic.story_reference_schema_version)
    topic_model.next_subtopic_id = topic.next_subtopic_id
    topic_model.language_code = topic.language_code
    topic_model.meta_tag_content = topic.meta_tag_content
    topic_model.practice_tab_is_displayed = topic.practice_tab_is_displayed
    topic_model.page_title_fragment_for_web = topic.page_title_fragment_for_web
    topic_model.skill_ids_for_diagnostic_test = (
        topic.skill_ids_for_diagnostic_test)
    change_dicts = [change.to_dict() for change in change_list]
    topic_model.commit(committer_id, commit_message, change_dicts)
    caching_services.delete_multi(
        caching_services.CACHE_NAMESPACE_TOPIC, None, [topic.id])
    topic.version += 1


def update_topic_and_subtopic_pages(
        committer_id, topic_id, change_list, commit_message):
    """Updates a topic and its subtopic pages. Commits changes.

    Args:
        committer_id: str. The id of the user who is performing the update
            action.
        topic_id: str. The topic id.
        change_list: list(TopicChange and SubtopicPageChange). These changes are
            applied in sequence to produce the resulting topic.
        commit_message: str or None. A description of changes made to the
            topic.

    Raises:
        ValueError. Current user does not have enough rights to edit a topic.
    """
    topic_rights = topic_fetchers.get_topic_rights(topic_id, strict=False)
    if topic_rights.topic_is_published and not commit_message:
        raise ValueError(
            'Expected a commit message, received none.')

    old_topic = topic_fetchers.get_topic_by_id(topic_id)
    (
        updated_topic, updated_subtopic_pages_dict,
        deleted_subtopic_ids, newly_created_subtopic_ids,
        updated_subtopic_pages_change_cmds_dict
    ) = apply_change_list(topic_id, change_list)

    if (
            old_topic.url_fragment != updated_topic.url_fragment and
            does_topic_with_url_fragment_exist(updated_topic.url_fragment)):
        raise utils.ValidationError(
            'Topic with URL Fragment \'%s\' already exists'
            % updated_topic.url_fragment)
    if (
            old_topic.name != updated_topic.name and
            does_topic_with_name_exist(updated_topic.name)):
        raise utils.ValidationError(
            'Topic with name \'%s\' already exists' % updated_topic.name)

    _save_topic(
        committer_id, updated_topic, commit_message, change_list
    )
    # The following loop deletes those subtopic pages that are already in the
    # datastore, which are supposed to be deleted in the current changelist.
    for subtopic_id in deleted_subtopic_ids:
        if subtopic_id not in newly_created_subtopic_ids:
            subtopic_page_services.delete_subtopic_page(
                committer_id, topic_id, subtopic_id)

    for subtopic_page_id, subtopic_page in updated_subtopic_pages_dict.items():
        subtopic_page_change_list = updated_subtopic_pages_change_cmds_dict[
            subtopic_page_id]
        subtopic_id = subtopic_page.get_subtopic_id_from_subtopic_page_id()
        # The following condition prevents the creation of subtopic pages that
        # were deleted above.
        if subtopic_id not in deleted_subtopic_ids:
            subtopic_page_services.save_subtopic_page(
                committer_id, subtopic_page, commit_message,
                subtopic_page_change_list)
    generate_topic_summary(topic_id)

    if old_topic.name != updated_topic.name:
        opportunity_services.update_opportunities_with_new_topic_name(
            updated_topic.id, updated_topic.name)


def delete_uncategorized_skill(user_id, topic_id, uncategorized_skill_id):
    """Removes skill with given id from the topic.

    Args:
        user_id: str. The id of the user who is performing the action.
        topic_id: str. The id of the topic from which to remove the skill.
        uncategorized_skill_id: str. The uncategorized skill to remove from the
            topic.
    """
    change_list = [topic_domain.TopicChange({
        'cmd': 'remove_uncategorized_skill_id',
        'uncategorized_skill_id': uncategorized_skill_id
    })]
    update_topic_and_subtopic_pages(
        user_id, topic_id, change_list,
        'Removed %s from uncategorized skill ids' % uncategorized_skill_id)


def add_uncategorized_skill(user_id, topic_id, uncategorized_skill_id):
    """Adds a skill with given id to the topic.

    Args:
        user_id: str. The id of the user who is performing the action.
        topic_id: str. The id of the topic to which the skill is to be added.
        uncategorized_skill_id: str. The id of the uncategorized skill to add
            to the topic.
    """
    change_list = [topic_domain.TopicChange({
        'cmd': 'add_uncategorized_skill_id',
        'new_uncategorized_skill_id': uncategorized_skill_id
    })]
    update_topic_and_subtopic_pages(
        user_id, topic_id, change_list,
        'Added %s to uncategorized skill ids' % uncategorized_skill_id)


def publish_story(topic_id, story_id, committer_id):
    """Marks the given story as published.

    Args:
        topic_id: str. The id of the topic.
        story_id: str. The id of the given story.
        committer_id: str. ID of the committer.

    Raises:
        Exception. The given story does not exist.
        Exception. The story is already published.
        Exception. The user does not have enough rights to publish the story.
    """
    def _are_nodes_valid_for_publishing(story_nodes):
        """Validates the story nodes before publishing.

        Args:
            story_nodes: list(dict(str, *)). The list of story nodes dicts.

        Raises:
            Exception. The story node doesn't contain any exploration id or the
                exploration id is invalid or isn't published yet.
        """
        exploration_id_list = []
        for node in story_nodes:
            if not node.exploration_id:
                raise Exception(
                    'Story node with id %s does not contain an '
                    'exploration id.' % node.id)
            exploration_id_list.append(node.exploration_id)
        story_services.validate_explorations_for_story(
            exploration_id_list, True)

    topic = topic_fetchers.get_topic_by_id(topic_id, strict=None)
    if topic is None:
        raise Exception('A topic with the given ID doesn\'t exist')
    user = user_services.get_user_actions_info(committer_id)
    if role_services.ACTION_CHANGE_STORY_STATUS not in user.actions:
        raise Exception(
            'The user does not have enough rights to publish the story.')

    story = story_fetchers.get_story_by_id(story_id, strict=False)
    if story is None:
        raise Exception('A story with the given ID doesn\'t exist')
    for node in story.story_contents.nodes:
        if node.id == story.story_contents.initial_node_id:
            _are_nodes_valid_for_publishing([node])

    topic.publish_story(story_id)
    change_list = [topic_domain.TopicChange({
        'cmd': topic_domain.CMD_PUBLISH_STORY,
        'story_id': story_id
    })]
    _save_topic(
        committer_id, topic, 'Published story with id %s' % story_id,
        change_list)
    generate_topic_summary(topic.id)
    # Create exploration opportunities corresponding to the story and linked
    # explorations.
    linked_exp_ids = story.story_contents.get_all_linked_exp_ids()
    opportunity_services.add_new_exploration_opportunities(
        story_id, linked_exp_ids)


def unpublish_story(topic_id, story_id, committer_id):
    """Marks the given story as unpublished.

    Args:
        topic_id: str. The id of the topic.
        story_id: str. The id of the given story.
        committer_id: str. ID of the committer.

    Raises:
        Exception. The given story does not exist.
        Exception. The story is already unpublished.
        Exception. The user does not have enough rights to unpublish the story.
    """
    user = user_services.get_user_actions_info(committer_id)
    if role_services.ACTION_CHANGE_STORY_STATUS not in user.actions:
        raise Exception(
            'The user does not have enough rights to unpublish the story.')
    topic = topic_fetchers.get_topic_by_id(topic_id, strict=None)
    if topic is None:
        raise Exception('A topic with the given ID doesn\'t exist')
    story = story_fetchers.get_story_by_id(story_id, strict=False)
    if story is None:
        raise Exception('A story with the given ID doesn\'t exist')
    topic.unpublish_story(story_id)
    change_list = [topic_domain.TopicChange({
        'cmd': topic_domain.CMD_UNPUBLISH_STORY,
        'story_id': story_id
    })]
    _save_topic(
        committer_id, topic, 'Unpublished story with id %s' % story_id,
        change_list)
    generate_topic_summary(topic.id)

    # Delete corresponding exploration opportunities and reject associated
    # translation suggestions.
    exp_ids = story.story_contents.get_all_linked_exp_ids()
    opportunity_services.delete_exploration_opportunities(exp_ids)
    suggestion_services.auto_reject_translation_suggestions_for_exp_ids(exp_ids)


def delete_canonical_story(user_id, topic_id, story_id):
    """Removes story with given id from the topic.

    NOTE TO DEVELOPERS: Presently, this function only removes story_reference
    from canonical_story_references list.

    Args:
        user_id: str. The id of the user who is performing the action.
        topic_id: str. The id of the topic from which to remove the story.
        story_id: str. The story to remove from the topic.
    """
    change_list = [topic_domain.TopicChange({
        'cmd': topic_domain.CMD_DELETE_CANONICAL_STORY,
        'story_id': story_id
    })]
    update_topic_and_subtopic_pages(
        user_id, topic_id, change_list,
        'Removed %s from canonical story ids' % story_id)


def add_canonical_story(user_id, topic_id, story_id):
    """Adds a story to the canonical story reference list of a topic.

    Args:
        user_id: str. The id of the user who is performing the action.
        topic_id: str. The id of the topic to which the story is to be added.
        story_id: str. The story to add to the topic.
    """
    change_list = [topic_domain.TopicChange({
        'cmd': topic_domain.CMD_ADD_CANONICAL_STORY,
        'story_id': story_id
    })]
    update_topic_and_subtopic_pages(
        user_id, topic_id, change_list,
        'Added %s to canonical story ids' % story_id)


def delete_additional_story(user_id, topic_id, story_id):
    """Removes story with given id from the topic.

    NOTE TO DEVELOPERS: Presently, this function only removes story_reference
    from additional_story_references list.

    Args:
        user_id: str. The id of the user who is performing the action.
        topic_id: str. The id of the topic from which to remove the story.
        story_id: str. The story to remove from the topic.
    """
    change_list = [topic_domain.TopicChange({
        'cmd': topic_domain.CMD_DELETE_ADDITIONAL_STORY,
        'story_id': story_id
    })]
    update_topic_and_subtopic_pages(
        user_id, topic_id, change_list,
        'Removed %s from additional story ids' % story_id)


def add_additional_story(user_id, topic_id, story_id):
    """Adds a story to the additional story reference list of a topic.

    Args:
        user_id: str. The id of the user who is performing the action.
        topic_id: str. The id of the topic to which the story is to be added.
        story_id: str. The story to add to the topic.
    """
    change_list = [topic_domain.TopicChange({
        'cmd': topic_domain.CMD_ADD_ADDITIONAL_STORY,
        'story_id': story_id
    })]
    update_topic_and_subtopic_pages(
        user_id, topic_id, change_list,
        'Added %s to additional story ids' % story_id)


def delete_topic(committer_id, topic_id, force_deletion=False):
    """Deletes the topic with the given topic_id.

    Args:
        committer_id: str. ID of the committer.
        topic_id: str. ID of the topic to be deleted.
        force_deletion: bool. If true, the topic and its history are fully
            deleted and are unrecoverable. Otherwise, the topic and all
            its history are marked as deleted, but the corresponding models are
            still retained in the datastore. This last option is the preferred
            one.

    Raises:
        ValueError. User does not have enough rights to delete a topic.
    """
    topic_rights_model = topic_models.TopicRightsModel.get(topic_id)
    topic_rights_model.delete(
        committer_id, feconf.COMMIT_MESSAGE_TOPIC_DELETED,
        force_deletion=force_deletion)

    # Delete the summary of the topic (regardless of whether
    # force_deletion is True or not).
    delete_topic_summary(topic_id)
    topic_model = topic_models.TopicModel.get(topic_id)
    for subtopic in topic_model.subtopics:
        subtopic_page_services.delete_subtopic_page(
            committer_id, topic_id, subtopic['id'])

    all_story_references = (
        topic_model.canonical_story_references +
        topic_model.additional_story_references)
    for story_reference in all_story_references:
        story_services.delete_story(
            committer_id, story_reference['story_id'],
            force_deletion=force_deletion)
    topic_model.delete(
        committer_id, feconf.COMMIT_MESSAGE_TOPIC_DELETED,
        force_deletion=force_deletion)

    feedback_services.delete_threads_for_multiple_entities(
        feconf.ENTITY_TYPE_TOPIC, [topic_id])

    # This must come after the topic is retrieved. Otherwise the memcache
    # key will be reinstated.
    caching_services.delete_multi(
        caching_services.CACHE_NAMESPACE_TOPIC, None, [topic_id])
    (
        opportunity_services
        .delete_exploration_opportunities_corresponding_to_topic(topic_id))


def delete_topic_summary(topic_id):
    """Delete a topic summary model.

    Args:
        topic_id: str. ID of the topic whose topic summary is to
            be deleted.
    """

    topic_models.TopicSummaryModel.get(topic_id).delete()


def update_story_and_topic_summary(
        committer_id, story_id, change_list, commit_message, topic_id):
    """Updates a story. Commits changes. Then generates a new
    topic summary.

    Args:
        committer_id: str. The id of the user who is performing the update
            action.
        story_id: str. The story id.
        change_list: list(StoryChange). These changes are applied in sequence to
            produce the resulting story.
        commit_message: str or None. A description of changes made to the
            story.
        topic_id: str. The id of the topic to which the story is belongs.
    """
    story_services.update_story(
        committer_id, story_id, change_list, commit_message)
    # Generate new TopicSummary after a Story has been updated to
    # make sure the TopicSummaryTile displays the correct number
    # of chapters on the classroom page.
    generate_topic_summary(topic_id)


def generate_topic_summary(topic_id):
    """Creates and stores a summary of the given topic.

    Args:
        topic_id: str. ID of the topic.
    """
    topic = topic_fetchers.get_topic_by_id(topic_id)
    topic_summary = compute_summary_of_topic(topic)
    save_topic_summary(topic_summary)


def compute_summary_of_topic(topic):
    """Create a TopicSummary domain object for a given Topic domain
    object and return it.

    Args:
        topic: Topic. The topic object for which the summary is to be computed.

    Returns:
        TopicSummary. The computed summary for the given topic.
    """
    canonical_story_count = 0
    additional_story_count = 0
    published_node_count = 0
    for reference in topic.canonical_story_references:
        if reference.story_is_published:
            canonical_story_count += 1
            story_summary = story_fetchers.get_story_summary_by_id(
                reference.story_id)
            published_node_count += len(story_summary.node_titles)
    for reference in topic.additional_story_references:
        if reference.story_is_published:
            additional_story_count += 1
    topic_model_canonical_story_count = canonical_story_count
    topic_model_additional_story_count = additional_story_count
    total_model_published_node_count = published_node_count
    topic_model_uncategorized_skill_count = len(topic.uncategorized_skill_ids)
    topic_model_subtopic_count = len(topic.subtopics)

    total_skill_count = topic_model_uncategorized_skill_count
    for subtopic in topic.subtopics:
        total_skill_count = total_skill_count + len(subtopic.skill_ids)

    topic_summary = topic_domain.TopicSummary(
        topic.id, topic.name, topic.canonical_name, topic.language_code,
        topic.description, topic.version, topic_model_canonical_story_count,
        topic_model_additional_story_count,
        topic_model_uncategorized_skill_count, topic_model_subtopic_count,
        total_skill_count, total_model_published_node_count,
        topic.thumbnail_filename, topic.thumbnail_bg_color, topic.url_fragment,
        topic.created_on, topic.last_updated
    )

    return topic_summary


def save_topic_summary(topic_summary):
    """Save a topic summary domain object as a TopicSummaryModel
    entity in the datastore.

    Args:
        topic_summary: TopicSummaryModel. The topic summary object to be saved
            in the datastore.
    """
    topic_summary_dict = {
        'name': topic_summary.name,
        'description': topic_summary.description,
        'canonical_name': topic_summary.canonical_name,
        'language_code': topic_summary.language_code,
        'version': topic_summary.version,
        'additional_story_count': topic_summary.additional_story_count,
        'canonical_story_count': topic_summary.canonical_story_count,
        'uncategorized_skill_count': topic_summary.uncategorized_skill_count,
        'subtopic_count': topic_summary.subtopic_count,
        'total_skill_count': topic_summary.total_skill_count,
        'total_published_node_count':
            topic_summary.total_published_node_count,
        'thumbnail_filename': topic_summary.thumbnail_filename,
        'thumbnail_bg_color': topic_summary.thumbnail_bg_color,
        'topic_model_last_updated': topic_summary.topic_model_last_updated,
        'topic_model_created_on': topic_summary.topic_model_created_on,
        'url_fragment': topic_summary.url_fragment
    }

    topic_summary_model = (
        topic_models.TopicSummaryModel.get_by_id(topic_summary.id))
    if topic_summary_model is not None:
        topic_summary_model.populate(**topic_summary_dict)
        topic_summary_model.update_timestamps()
        topic_summary_model.put()
    else:
        topic_summary_dict['id'] = topic_summary.id
        model = topic_models.TopicSummaryModel(**topic_summary_dict)
        model.update_timestamps()
        model.put()


def publish_topic(topic_id, committer_id):
    """Marks the given topic as published.

    Args:
        topic_id: str. The id of the given topic.
        committer_id: str. ID of the committer.

    Raises:
        Exception. The given topic does not exist.
        Exception. The topic is already published.
        Exception. The user does not have enough rights to publish the topic.
    """
    topic_rights = topic_fetchers.get_topic_rights(topic_id, strict=False)
    if topic_rights is None:
        raise Exception('The given topic does not exist')
    topic = topic_fetchers.get_topic_by_id(topic_id)
    topic.validate(strict=True)
    user = user_services.get_user_actions_info(committer_id)
    if role_services.ACTION_CHANGE_TOPIC_STATUS not in user.actions:
        raise Exception(
            'The user does not have enough rights to publish the topic.')

    if topic_rights.topic_is_published:
        raise Exception('The topic is already published.')
    topic_rights.topic_is_published = True
    commit_cmds = [topic_domain.TopicRightsChange({
        'cmd': topic_domain.CMD_PUBLISH_TOPIC
    })]
    save_topic_rights(
        topic_rights, committer_id, 'Published the topic', commit_cmds)


def unpublish_topic(topic_id, committer_id):
    """Marks the given topic as unpublished.

    Args:
        topic_id: str. The id of the given topic.
        committer_id: str. ID of the committer.

    Raises:
        Exception. The given topic does not exist.
        Exception. The topic is already unpublished.
        Exception. The user does not have enough rights to unpublish the topic.
    """
    topic_rights = topic_fetchers.get_topic_rights(topic_id, strict=False)
    if topic_rights is None:
        raise Exception('The given topic does not exist')
    user = user_services.get_user_actions_info(committer_id)
    if role_services.ACTION_CHANGE_TOPIC_STATUS not in user.actions:
        raise Exception(
            'The user does not have enough rights to unpublish the topic.')

    if not topic_rights.topic_is_published:
        raise Exception('The topic is already unpublished.')
    topic_rights.topic_is_published = False
    commit_cmds = [topic_domain.TopicRightsChange({
        'cmd': topic_domain.CMD_UNPUBLISH_TOPIC
    })]
    save_topic_rights(
        topic_rights, committer_id, 'Unpublished the topic', commit_cmds)


def save_topic_rights(topic_rights, committer_id, commit_message, commit_cmds):
    """Saves a TopicRights domain object to the datastore.

    Args:
        topic_rights: TopicRights. The rights object for the given
            topic.
        committer_id: str. ID of the committer.
        commit_message: str. Descriptive message for the commit.
        commit_cmds: list(TopicRightsChange). A list of commands describing
            what kind of commit was done.
    """

    model = topic_models.TopicRightsModel.get(topic_rights.id, strict=False)

    model.manager_ids = topic_rights.manager_ids
    model.topic_is_published = topic_rights.topic_is_published
    commit_cmd_dicts = [commit_cmd.to_dict() for commit_cmd in commit_cmds]
    model.commit(committer_id, commit_message, commit_cmd_dicts)


def create_new_topic_rights(topic_id, committer_id):
    """Creates a new topic rights object and saves it to the datastore.

    Args:
        topic_id: str. ID of the topic.
        committer_id: str. ID of the committer.
    """
    topic_rights = topic_domain.TopicRights(topic_id, [], False)
    commit_cmds = [{'cmd': topic_domain.CMD_CREATE_NEW}]

    topic_models.TopicRightsModel(
        id=topic_rights.id,
        manager_ids=topic_rights.manager_ids,
        topic_is_published=topic_rights.topic_is_published
    ).commit(committer_id, 'Created new topic rights', commit_cmds)


def filter_published_topic_ids(topic_ids):
    """Given list of topic IDs, returns the IDs of all topics that are published
    in that list.

    Args:
        topic_ids: list(str). The list of topic ids.

    Returns:
        list(str). The topic IDs in the passed in list corresponding to
        published topics.
    """
    topic_rights_models = topic_models.TopicRightsModel.get_multi(topic_ids)
    published_topic_ids = []
    for ind, model in enumerate(topic_rights_models):
        if model is None:
            continue
        rights = topic_fetchers.get_topic_rights_from_model(model)
        if rights.topic_is_published:
            published_topic_ids.append(topic_ids[ind])
    return published_topic_ids


def check_can_edit_topic(user, topic_rights):
    """Checks whether the user can edit the given topic.

    Args:
        user: UserActionsInfo. Object having user_id, role and actions for
            given user.
        topic_rights: TopicRights or None. Rights object for the given topic.

    Returns:
        bool. Whether the given user can edit the given topic.
    """
    if topic_rights is None:
        return False
    if role_services.ACTION_EDIT_ANY_TOPIC in user.actions:
        return True
    if role_services.ACTION_EDIT_OWNED_TOPIC not in user.actions:
        return False
    if topic_rights.is_manager(user.user_id):
        return True

    return False


def deassign_user_from_all_topics(committer, user_id):
    """Deassigns given user from all topics assigned to them.

    Args:
        committer: UserActionsInfo. UserActionsInfo object for the user
            who is performing the action.
        user_id: str. The ID of the user.

    Raises:
        Exception. The committer does not have rights to modify a role.
    """
    topic_rights_list = topic_fetchers.get_topic_rights_with_user(user_id)
    for topic_rights in topic_rights_list:
        topic_rights.manager_ids.remove(user_id)
        commit_cmds = [topic_domain.TopicRightsChange({
            'cmd': topic_domain.CMD_REMOVE_MANAGER_ROLE,
            'removed_user_id': user_id
        })]
        save_topic_rights(
            topic_rights, committer.user_id,
            'Removed all assigned topics from %s' % (
                user_services.get_username(user_id)
            ),
            commit_cmds
        )


def deassign_manager_role_from_topic(committer, user_id, topic_id):
    """Deassigns given user from all topics assigned to them.

    Args:
        committer: UserActionsInfo. UserActionsInfo object for the user
            who is performing the action.
        user_id: str. The ID of the user.
        topic_id: str. The ID of the topic.

    Raises:
        Exception. The committer does not have rights to modify a role.
    """
    topic_rights = topic_fetchers.get_topic_rights(topic_id)
    if user_id not in topic_rights.manager_ids:
        raise Exception('User does not have manager rights in topic.')

    topic_rights.manager_ids.remove(user_id)
    commit_cmds = [topic_domain.TopicRightsChange({
        'cmd': topic_domain.CMD_REMOVE_MANAGER_ROLE,
        'removed_user_id': user_id
    })]
    save_topic_rights(
        topic_rights,
        committer.user_id,
        'Removed all assigned topics from %s' % (
            user_services.get_username(user_id)
        ),
        commit_cmds
    )


def assign_role(committer, assignee, new_role, topic_id):
    """Assigns a new role to the user.

    Args:
        committer: UserActionsInfo. UserActionsInfo object for the user
            who is performing the action.
        assignee: UserActionsInfo. UserActionsInfo object for the user
            whose role is being changed.
        new_role: str. The name of the new role. Possible values are:
            ROLE_MANAGER.
        topic_id: str. ID of the topic.

    Raises:
        Exception. The committer does not have rights to modify a role.
        Exception. The assignee is already a manager for the topic.
        Exception. The assignee doesn't have enough rights to become a manager.
        Exception. The role is invalid.
    """
    committer_id = committer.user_id
    topic_rights = topic_fetchers.get_topic_rights(topic_id)
    if (role_services.ACTION_MODIFY_CORE_ROLES_FOR_ANY_ACTIVITY not in
            committer.actions):
        logging.error(
            'User %s tried to allow user %s to be a %s of topic %s '
            'but was refused permission.' % (
                committer_id, assignee.user_id, new_role, topic_id))
        raise Exception(
            'UnauthorizedUserException: Could not assign new role.')

    assignee_username = user_services.get_username(assignee.user_id)
    if role_services.ACTION_EDIT_OWNED_TOPIC not in assignee.actions:
        raise Exception(
            'The assignee doesn\'t have enough rights to become a manager.')

    old_role = topic_domain.ROLE_NONE
    if topic_rights.is_manager(assignee.user_id):
        old_role = topic_domain.ROLE_MANAGER

    if new_role == topic_domain.ROLE_MANAGER:
        if topic_rights.is_manager(assignee.user_id):
            raise Exception('This user already is a manager for this topic')
        topic_rights.manager_ids.append(assignee.user_id)
    elif new_role == topic_domain.ROLE_NONE:
        if topic_rights.is_manager(assignee.user_id):
            topic_rights.manager_ids.remove(assignee.user_id)
        else:
            old_role = topic_domain.ROLE_NONE
    else:
        raise Exception('Invalid role: %s' % new_role)

    commit_message = rights_domain.ASSIGN_ROLE_COMMIT_MESSAGE_TEMPLATE % (
        assignee_username, old_role, new_role)
    commit_cmds = [topic_domain.TopicRightsChange({
        'cmd': topic_domain.CMD_CHANGE_ROLE,
        'assignee_id': assignee.user_id,
        'old_role': old_role,
        'new_role': new_role
    })]

    save_topic_rights(topic_rights, committer_id, commit_message, commit_cmds)


def get_story_titles_in_topic(topic):
    """Returns titles of the stories present in the topic.

    Args:
        topic: Topic. The topic domain objects.

    Returns:
        list(str). The list of story titles in the topic.
    """
    canonical_story_references = topic.canonical_story_references
    story_ids = [story.story_id for story in canonical_story_references]
    stories = story_fetchers.get_stories_by_ids(story_ids)
    story_titles = [story.title for story in stories if story is not None]
    return story_titles


def update_thumbnail_filename(
    topic: topic_domain.Topic, new_thumbnail_filename: Optional[str]
) -> None:
    """Updates the thumbnail filename and file size in a topic object.

    Args:
        topic: topic_domain.Topic. The topic domain object whose thumbnail
            is to be updated.
        new_thumbnail_filename: str|None. The updated thumbnail filename
            for the topic.

    Raises:
        Exception. The thumbnail does not exist for expected topic in
            the filesystem.
    """
    fs = fs_services.GcsFileSystem(feconf.ENTITY_TYPE_TOPIC, topic.id)
    filepath = '%s/%s' % (
        constants.ASSET_TYPE_THUMBNAIL, new_thumbnail_filename)
    if fs.isfile(filepath):  # type: ignore[no-untyped-call]
        thumbnail_size_in_bytes = len(fs.get(filepath))
        topic.update_thumbnail_filename_and_size(
            new_thumbnail_filename, thumbnail_size_in_bytes)
    else:
        raise Exception(
            'The thumbnail %s for topic with id %s does not exist'
            ' in the filesystem.' % (new_thumbnail_filename, topic.id))


def update_subtopic_thumbnail_filename(
    topic: topic_domain.Topic,
    subtopic_id: int,
    new_thumbnail_filename: str
) -> None:
    """Updates the thumbnail filename and file size in a subtopic.

    Args:
        topic: topic_domain.Topic. The topic domain object containing
            the subtopic whose thumbnail is to be updated.
        subtopic_id: int. The id of the subtopic to edit.
        new_thumbnail_filename: str. The new thumbnail filename for the
            subtopic.

    Raises:
        Exception. The thumbnail does not exist for expected topic in
            the filesystem.
    """
    fs = fs_services.GcsFileSystem(feconf.ENTITY_TYPE_TOPIC, topic.id)
    filepath = '%s/%s' % (
        constants.ASSET_TYPE_THUMBNAIL, new_thumbnail_filename)
    if fs.isfile(filepath):  # type: ignore[no-untyped-call]
        thumbnail_size_in_bytes = len(fs.get(filepath))
        topic.update_subtopic_thumbnail_filename_and_size(
            subtopic_id, new_thumbnail_filename, thumbnail_size_in_bytes)
    else:
        raise Exception(
            'The thumbnail %s for subtopic with topic_id %s does not exist'
            ' in the filesystem.' % (new_thumbnail_filename, topic.id))
