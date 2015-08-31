# -*- coding: utf-8; -*-
#
# This file is part of Superdesk.
#
# Copyright 2013, 2014 Sourcefabric z.u. and contributors.
#
# For the full copyright and license information, please see the
# AUTHORS and LICENSE files distributed with this source code, or
# at https://www.sourcefabric.org/superdesk/license

from eve.utils import config
from eve.versioning import resolve_document_version
from flask import request

import superdesk
from apps.tasks import send_to
from superdesk import get_resource_service
from superdesk.errors import SuperdeskApiError, InvalidStateTransitionError
from superdesk.metadata.item import ITEM_STATE, CONTENT_STATE
from superdesk.resource import Resource
from superdesk.services import BaseService
from superdesk.metadata.utils import item_url
from apps.archive.common import insert_into_versions, item_operations,\
    ITEM_OPERATION, set_sign_off, get_user
from apps.archive.archive import SOURCE as ARCHIVE
from superdesk.workflow import is_workflow_state_transition_valid

ITEM_MOVE = 'move'
item_operations.append(ITEM_MOVE)


class MoveResource(Resource):
    endpoint_name = 'move'
    resource_title = endpoint_name

    schema = {
        'task': {
            'type': 'dict',
            'required': True,
            'schema': {
                'desk': Resource.rel('desks', False, required=True),
                'stage': Resource.rel('stages', False, required=True)
            }
        }
    }

    url = 'archive/<{0}:guid>/move'.format(item_url)

    resource_methods = ['POST']
    item_methods = []

    privileges = {'POST': 'move'}


class MoveService(BaseService):
    def create(self, docs, **kwargs):
        guid_of_item_to_be_moved = request.view_args['guid']
        guid_of_moved_items = []

        for doc in docs:
            guid_of_moved_items.append(self.move_content(guid_of_item_to_be_moved, doc)['guid'])

        return guid_of_moved_items

    def move_content(self, id, doc):
        archive_service = get_resource_service(ARCHIVE)
        archived_doc = archive_service.find_one(req=None, _id=id)

        if not archived_doc:
            raise SuperdeskApiError.notFoundError('Fail to found item with guid: %s' % id)

        current_stage_of_item = archived_doc.get('task', {}).get('stage')
        if current_stage_of_item and str(current_stage_of_item) == str(doc.get('task', {}).get('stage')):
            raise SuperdeskApiError.preconditionFailedError(message='Move is not allowed within the same stage.')

        if not is_workflow_state_transition_valid('submit_to_desk', archived_doc[ITEM_STATE]):
            raise InvalidStateTransitionError()

        original = dict(archived_doc)
        user = get_user()

        send_to(doc=archived_doc, desk_id=doc.get('task', {}).get('desc'), stage_id=doc.get('task', {}).get('stage'),
                user_id=user.get(config.ID_FIELD))

        if archived_doc[ITEM_STATE] not in {CONTENT_STATE.PUBLISHED, CONTENT_STATE.SCHEDULED, CONTENT_STATE.KILLED}:
            archived_doc[ITEM_STATE] = CONTENT_STATE.SUBMITTED
        archived_doc[ITEM_OPERATION] = ITEM_MOVE

        set_sign_off(archived_doc, original=original)
        resolve_document_version(archived_doc, ARCHIVE, 'PATCH', original)

        del archived_doc[config.ID_FIELD]
        archive_service.update(original[config.ID_FIELD], archived_doc, original)

        insert_into_versions(id_=original[config.ID_FIELD])

        return archived_doc


superdesk.workflow_action(
    name='submit_to_desk',
    include_states=['draft', 'fetched', 'routed', 'submitted', 'in_progress', 'published', 'scheduled'],
    privileges=['archive', 'move']
)
