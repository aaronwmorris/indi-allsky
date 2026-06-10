"""Remove OIDC config from database

Revision ID: 7d8e9f0a1b2c
Revises: 44b9d0b5e3a2
Create Date: 2026-06-10 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7d8e9f0a1b2c'
down_revision = '44b9d0b5e3a2'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    
    # Reflect the config table
    config_table = sa.Table(
        'config',
        sa.MetaData(),
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('data', sa.JSON)
    )
    
    results = connection.execute(sa.select(config_table.c.id, config_table.c.data)).fetchall()
    
    keys_to_remove = [
        'CLIENT_ID', 
        'CLIENT_SECRET', 
        'CLIENT_SECRET_E', 
        'DISCOVERY_URL', 
        'SCOPES', 
        'GROUP_ADMIN', 
        'PKCE'
    ]
    
    for row in results:
        config_id = row.id
        data = row.data
        
        if data and 'OIDC' in data:
            modified = False
            oidc_data = data['OIDC']
            for key in keys_to_remove:
                if key in oidc_data:
                    del oidc_data[key]
                    modified = True
            
            if modified:
                connection.execute(
                    config_table.update().where(config_table.c.id == config_id).values(data=data)
                )


def downgrade():
    pass
