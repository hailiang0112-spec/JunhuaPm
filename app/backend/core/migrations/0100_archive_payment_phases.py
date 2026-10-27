# archive 代理：付款节点支持多个关联工段（PAGE-F15-01「关联工段 可多选」）并记录标记已付的操作人（AC-F15-03 留痕）。
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_runtime_grants'),
    ]

    operations = [
        migrations.AddField(
            model_name='paymentmilestone',
            name='paid_by',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='paymentmilestone',
            name='phases',
            field=models.ManyToManyField(related_name='+', to='core.phase'),
        ),
    ]
