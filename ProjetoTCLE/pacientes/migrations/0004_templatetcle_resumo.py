from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pacientes', '0003_alter_documentoemitido_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='templatetcle',
            name='resumo',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Breve descrição do documento, exibida no card do template na Biblioteca.',
                max_length=160,
                verbose_name='Resumo do Template',
            ),
        ),
    ]
